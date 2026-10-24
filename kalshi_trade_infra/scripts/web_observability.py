"""One-time AWS setup for tau-trading.com speed and monitoring (applied 2026-10-24).

Kept so the setup can be re-created or audited; each section was run once by hand with the
cloud env's credentials (`env -u AWS_PROFILE python3 scripts/web_observability.py <step>`).

  logs     CloudFront access logs (v2) -> CloudWatch Logs /tau/cloudfront-access, 14 days,
           plus CloudFront additional metrics (OriginLatency, per-code error rates).
  static   /static/* cached at the edge by path + ?v= (bundles are content-hashed), br/gzip,
           and a 30s origin keep-alive.
  monitors Route 53 /healthz check, alarms tau-site-down / tau-5xx-rate / tau-origin-slow to the
           kalshi-live-alerts SNS topic, and the tau-reliability CloudWatch dashboard.

Monthly cost: about $3 (health check ~$1.75, 3 alarms $0.30, extra metrics, a few MB of logs).
Query p50/p95 per route in Logs Insights on /tau/cloudfront-access with `time-taken`.
"""
import sys


def logs():
    import boto3, json
    acct = "568386354218"; dist = "EEQ00Y93RTB1K"
    logs = boto3.client("logs", region_name="us-east-1")
    lg = "/tau/cloudfront-access"
    try: logs.create_log_group(logGroupName=lg)
    except logs.exceptions.ResourceAlreadyExistsException: pass
    logs.put_retention_policy(logGroupName=lg, retentionInDays=14)
    lg_arn = "arn:aws:logs:us-east-1:%s:log-group:%s" % (acct, lg)
    src = logs.put_delivery_source(name="tau-cf-access", resourceArn="arn:aws:cloudfront::%s:distribution/%s" % (acct, dist), logType="ACCESS_LOGS")
    print("source", src["deliverySource"]["name"])
    dst = logs.put_delivery_destination(name="tau-cf-access-cwl", outputFormat="json", deliveryDestinationConfiguration={"destinationResourceArn": lg_arn})
    print("dest", dst["deliveryDestination"]["arn"])
    try:
        d = logs.create_delivery(deliverySourceName="tau-cf-access", deliveryDestinationArn=dst["deliveryDestination"]["arn"])
        print("delivery", d["delivery"]["id"])
    except Exception as e: print("delivery err", e)
    cf = boto3.client("cloudfront")
    cf.create_monitoring_subscription(DistributionId=dist, MonitoringSubscription={
        "RealtimeMetricsSubscriptionConfig": {"RealtimeMetricsSubscriptionStatus": "Enabled"}})


def static():
    import boto3, json, copy
    cf = boto3.client("cloudfront")
    name = "tau-static-versioned"
    pol = None
    for item in cf.list_cache_policies(Type="custom").get("CachePolicyList", {}).get("Items", []):
        if item["CachePolicy"]["CachePolicyConfig"]["Name"] == name: pol = item["CachePolicy"]["Id"]
    if not pol:
        pol = cf.create_cache_policy(CachePolicyConfig={
            "Name": name, "Comment": "Tau versioned static bundles: cache by path + v, compress at edge",
            "MinTTL": 0, "DefaultTTL": 86400, "MaxTTL": 31536000,
            "ParametersInCacheKeyAndForwardedToOrigin": {
                "EnableAcceptEncodingGzip": True, "EnableAcceptEncodingBrotli": True,
                "HeadersConfig": {"HeaderBehavior": "none"}, "CookiesConfig": {"CookieBehavior": "none"},
                "QueryStringsConfig": {"QueryStringBehavior": "whitelist", "QueryStrings": {"Quantity": 1, "Items": ["v"]}}}})["CachePolicy"]["Id"]
    print("policy", pol)
    r = cf.get_distribution_config(Id="EEQ00Y93RTB1K"); cfg, etag = r["DistributionConfig"], r["ETag"]
    d = cfg["DefaultCacheBehavior"]
    beh = {"PathPattern": "/static/*", "TargetOriginId": d["TargetOriginId"], "ViewerProtocolPolicy": "redirect-to-https",
           "AllowedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"], "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}},
           "SmoothStreaming": False, "Compress": True, "CachePolicyId": pol,
           "LambdaFunctionAssociations": {"Quantity": 0}, "FunctionAssociations": {"Quantity": 0},
           "FieldLevelEncryptionId": "", "TrustedSigners": {"Enabled": False, "Quantity": 0}, "TrustedKeyGroups": {"Enabled": False, "Quantity": 0}}
    items = [b for b in cfg["CacheBehaviors"].get("Items", []) if b["PathPattern"] != "/static/*"] + [beh]
    cfg["CacheBehaviors"] = {"Quantity": len(items), "Items": items}
    for o in cfg["Origins"]["Items"]:
        if o["Id"] == d["TargetOriginId"]:
            o["CustomOriginConfig"]["OriginKeepaliveTimeout"] = 30
    res = cf.update_distribution(Id="EEQ00Y93RTB1K", IfMatch=etag, DistributionConfig=cfg)
    print(res["Distribution"]["Status"], [b["PathPattern"] for b in res["Distribution"]["DistributionConfig"]["CacheBehaviors"]["Items"]])


def monitors():
    import boto3, json, uuid
    topic = "arn:aws:sns:us-east-1:568386354218:kalshi-live-alerts"
    r53 = boto3.client("route53"); cw = boto3.client("cloudwatch", region_name="us-east-1")
    hc = r53.create_health_check(CallerReference="tau-healthz-" + uuid.uuid4().hex[:8], HealthCheckConfig={
        "Type": "HTTPS", "FullyQualifiedDomainName": "tau-trading.com", "ResourcePath": "/healthz", "Port": 443,
        "RequestInterval": 30, "FailureThreshold": 3, "EnableSNI": True, "MeasureLatency": True})["HealthCheck"]["Id"]
    r53.change_tags_for_resource(ResourceType="healthcheck", ResourceId=hc, AddTags=[{"Key": "Name", "Value": "tau-trading.com /healthz"}])
    print("healthcheck", hc)
    cf = [{"Name": "DistributionId", "Value": "EEQ00Y93RTB1K"}, {"Name": "Region", "Value": "Global"}]
    common = dict(AlarmActions=[topic], OKActions=[topic], ActionsEnabled=True)
    cw.put_metric_alarm(AlarmName="tau-site-down", AlarmDescription="tau-trading.com/healthz failing from Route 53 checkers for 2+ minutes (box, app or CloudFront down).",
        Namespace="AWS/Route53", MetricName="HealthCheckStatus", Dimensions=[{"Name": "HealthCheckId", "Value": hc}],
        Statistic="Minimum", Period=60, EvaluationPeriods=2, DatapointsToAlarm=2, Threshold=1, ComparisonOperator="LessThanThreshold",
        TreatMissingData="breaching", **common)
    cw.put_metric_alarm(AlarmName="tau-5xx-rate", AlarmDescription="More than 10% of tau-trading.com requests returned 5xx for 10 minutes.",
        Namespace="AWS/CloudFront", MetricName="5xxErrorRate", Dimensions=cf, Statistic="Average", Period=300,
        EvaluationPeriods=2, DatapointsToAlarm=2, Threshold=10, ComparisonOperator="GreaterThanThreshold", TreatMissingData="notBreaching", **common)
    cw.put_metric_alarm(AlarmName="tau-origin-slow", AlarmDescription="tau-trading.com origin p95 latency above 1.5s for 15 minutes.",
        Namespace="AWS/CloudFront", MetricName="OriginLatency", Dimensions=cf, ExtendedStatistic="p95", Period=300,
        EvaluationPeriods=3, DatapointsToAlarm=3, Threshold=1500, ComparisonOperator="GreaterThanThreshold", TreatMissingData="notBreaching", **common)
    dash = {"widgets": [
      {"type": "metric", "x": 0, "y": 0, "width": 12, "height": 6, "properties": {"title": "Origin latency p50/p95 (ms)", "region": "us-east-1", "stat": "p95", "period": 300,
         "metrics": [["AWS/CloudFront", "OriginLatency", "DistributionId", "EEQ00Y93RTB1K", "Region", "Global", {"stat": "p50"}], ["...", {"stat": "p95"}]]}},
      {"type": "metric", "x": 12, "y": 0, "width": 12, "height": 6, "properties": {"title": "Error rate (%)", "region": "us-east-1", "stat": "Average", "period": 300,
         "metrics": [["AWS/CloudFront", "5xxErrorRate", "DistributionId", "EEQ00Y93RTB1K", "Region", "Global"], [".", "4xxErrorRate", ".", ".", ".", "."]]}},
      {"type": "metric", "x": 0, "y": 6, "width": 12, "height": 6, "properties": {"title": "Requests / 5 min", "region": "us-east-1", "stat": "Sum", "period": 300,
         "metrics": [["AWS/CloudFront", "Requests", "DistributionId", "EEQ00Y93RTB1K", "Region", "Global"]]}},
      {"type": "metric", "x": 12, "y": 6, "width": 12, "height": 6, "properties": {"title": "Uptime (Route 53 /healthz)", "region": "us-east-1", "stat": "Minimum", "period": 60,
         "metrics": [["AWS/Route53", "HealthCheckStatus", "HealthCheckId", hc]]}},
      {"type": "metric", "x": 0, "y": 12, "width": 12, "height": 6, "properties": {"title": "RDS CPU / connections", "region": "us-east-1", "stat": "Average", "period": 300,
         "metrics": [["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", "kalshi-trade-mysql"], [".", "DatabaseConnections", ".", "."]]}},
      {"type": "metric", "x": 12, "y": 12, "width": 12, "height": 6, "properties": {"title": "Web box CPU", "region": "us-east-1", "stat": "Average", "period": 300,
         "metrics": [["AWS/EC2", "CPUUtilization", "InstanceId", "i-077d6f7873e7836ba"]]}}]}
    cw.put_dashboard(DashboardName="tau-reliability", DashboardBody=json.dumps(dash))
    print("ok")


if __name__ == "__main__":
    {"logs": logs, "static": static, "monitors": monitors}[sys.argv[1]]()
