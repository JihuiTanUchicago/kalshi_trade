from data_pipeline.architecture.contracts import RiskContext, RiskDecision


class DummyRiskEngine:
    """
    Bypass risk engine for environments where no independent risk policy exists yet.
    """

    def evaluate(self, ctx: RiskContext) -> RiskDecision:
        return RiskDecision(allowed=True, state=ctx.risk_state, reasons=[])


class LiveSettingsRiskEngine:
    """
    Risk policy adapter backed by current live settings + portfolio state.
    """

    def evaluate(self, ctx: RiskContext) -> RiskDecision:
        reasons = []
        if str(ctx.risk_state).upper() == "RED":
            reasons.append("RISK_RED")
        if ctx.near_expiry:
            reasons.append("NEAR_EXPIRY")
        if not ctx.signal:
            reasons.append("NO_SIGNAL")
        if int(ctx.risk_meta.get("open_count", 0)) >= int(ctx.cfg["max_concurrent_positions"]):
            reasons.append("MAX_CONCURRENT_POSITIONS")
        if float(ctx.risk_meta.get("open_notional", 0.0)) >= float(ctx.cfg["max_open_notional"]):
            reasons.append("MAX_OPEN_NOTIONAL")
        return RiskDecision(allowed=(len(reasons) == 0), state=ctx.risk_state, reasons=reasons)
