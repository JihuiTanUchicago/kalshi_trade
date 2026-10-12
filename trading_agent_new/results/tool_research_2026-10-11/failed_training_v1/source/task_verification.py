"""Independent arithmetic reconstruction using rational numbers and input facts."""
from datetime import datetime
from fractions import Fraction
import math

from .common import GateError


def equal(expected,actual):
    if isinstance(expected,dict):return isinstance(actual,dict) and set(expected)==set(actual) and all(equal(v,actual[k]) for k,v in expected.items())
    if type(expected) in (int,float,Fraction):
        return type(actual) in (int,float) and math.isfinite(actual) and abs(float(expected)-actual)<=1e-8*max(1,abs(float(expected)))
    return type(expected) is type(actual) and expected==actual


def reconstruct(operation,x):
    f=lambda n:Fraction(str(n))
    if operation=='select_asof':
        at=datetime.fromisoformat(x['decision_at'].replace('Z','+00:00'))
        return {'usable_ids':sorted(r['id'] for r in x['rows'] if all(datetime.fromisoformat(r[k].replace('Z','+00:00'))<=at for k in ('effective_at','available_at')))}
    if operation=='holding_return':
        quantity=x['initial_shares'];claims=Fraction(0);rows=x['rows']
        for row in rows[1:]:quantity*=f(row['split']);claims+=quantity*f(row['dividend'])
        return {'ending_shares':int(quantity),'total_return':(quantity*f(rows[-1]['close'])+claims)/(x['initial_shares']*f(rows[0]['close']))-1}
    if operation=='account_actions':
        quantity=x['opening_shares'];paid=Fraction(0);unpaid=Fraction(0)
        for event in x['events']:
            quantity*=f(event['split']);amount=quantity*f(event['dividend'])
            if event['paid']:paid+=amount
            else:unpaid+=amount
        return {'ending_shares':int(quantity),'cash_change':paid,'unpaid_dividend_claim':unpaid,
                'nav_change':quantity*f(x['ending_price'])+paid+unpaid-x['opening_shares']*f(x['opening_price'])}
    if operation=='compare_assumptions':
        from .common import canonical
        names=set(x['baseline'])|set(x['candidate'])
        wrong=sorted(k for k in names if k not in x['baseline'] or k not in x['candidate'] or canonical(x['baseline'][k])!=canonical(x['candidate'][k]))
        return {'comparable':not wrong,'mismatched_assumptions':wrong}
    if operation=='attribute_costs':
        a=f(x['candidate_net_sharpe'])-f(x['baseline_net_sharpe']);b=f(x['candidate_cost_free_sharpe'])-f(x['baseline_cost_free_sharpe'])
        return {'net_gain':a,'cost_free_gain':b,'modeled_cost_contribution':a-b,'turnover_change':(f(x['candidate_traded_notional'])-f(x['baseline_traded_notional']))/f(x['average_nav'])}
    if operation=='summarize_exposure':
        positions=list(map(f,x['signed_market_values']));nav=f(x['nav'])
        return {'gross_weight':sum(abs(v) for v in positions)/nav,'net_weight':sum(positions)/nav,
                'free_cash':f(x['cash'])-f(x['restricted_collateral'])-f(x['short_dividend_obligation'])}
    if operation=='apply_research_gates':
        failures=[f(x['sharpe_gain'])<Fraction(1,10),f(x['paired_lower'])<=0,f(x['double_cost_gain'])<=0,
                  f(x['drawdown_deterioration'])>Fraction(2,100),x['bootstrap_samples']<2000,x['blocks']<2,x['block_length']<21,not x['verification_passed']]
        return {'decision':'reject' if any(failures) else 'advance_to_paper_qualification' if x['qualified_data'] else 'revise_data_qualification'}
    if operation=='reconcile_fills':
        first={};bad=False
        for e in x['executions']:
            if e['id'] in first and first[e['id']]!=e['quantity']:bad=True
            first.setdefault(e['id'],e['quantity'])
        count=sum(first.values());bad |= count>x['requested_quantity'] or x['status']=='filled' and count!=x['requested_quantity']
        action='pause' if bad else 'closed' if x['status']=='filled' else 'wait' if x['status']=='acknowledged' else 'reconcile'
        return {'next_action':action,'resubmit':False,'filled_quantity':count}
    raise GateError('Unregistered independent reconstruction')


def verify(operation,payload,result):
    from .analysis_tools import CATALOG
    if result['kind']!=CATALOG[operation]['output_kind']:raise GateError('Analytical output kind changed')
    if not equal(reconstruct(operation,payload),result['report']):raise GateError('Independent analytical reconstruction disagreed')
    if operation=='select_asof':
        wanted=result['report']['usable_ids'];kept=result['payload']['rows']
        if sorted(r['id'] for r in kept)!=wanted:raise GateError('Filtered payload differs from verified usable identities')
        source={r['id']:r for r in payload['rows']}
        if any(row!=source[row['id']] for row in kept):raise GateError('Filtering changed an observation')
        if result['payload']['decision_at']!=payload['decision_at'] or result['payload']['initial_shares']!=payload['initial_shares']:raise GateError('Filtering changed the decision time or opening position')
        times=[datetime.fromisoformat(r['effective_at'].replace('Z','+00:00')) for r in kept]
        if times!=sorted(times):raise GateError('Filtered observations are out of order')
    elif result['payload']!=result['report']:raise GateError('Derived payload differs from the verified report')
    return True
