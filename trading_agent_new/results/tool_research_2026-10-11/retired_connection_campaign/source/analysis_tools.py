"""Small, allowlisted host calculations. No code execution, IO or broker access."""
from decimal import Decimal
from datetime import datetime, timezone
import math

from .common import GateError, canonical

CATALOG = {
 'select_asof':{'input_kind':'market_history','output_kind':'asof_history','description':'Keep rows whose effective_at AND available_at are no later than decision_at; sort by effective_at. Returns usable_ids and a filtered history for holding_return.'},
 'holding_return':{'input_kind':'asof_history','output_kind':'return_report','description':'Starting at the first filtered close, apply later splits before dividends; retain dividends as cash/claims without reinvestment. Return total_return and ending_shares. Requires select_asof output.'},
 'account_actions':{'input_kind':'action_account','output_kind':'action_report','description':'Apply a sequence of splits and dividends to signed shares. Paid dividends affect cash; unpaid entitlements affect signed claims. Return ending_shares, cash_change, unpaid_dividend_claim and nav_change.'},
 'compare_assumptions':{'input_kind':'paired_assumptions','output_kind':'comparison_report','description':'Compare all baseline and candidate non-signal fields, including missing keys. Return comparable and sorted mismatched_assumptions.'},
 'attribute_costs':{'input_kind':'cost_controls','output_kind':'cost_report','description':'Compute candidate-minus-baseline net_gain, cost_free_gain, modeled_cost_contribution=net minus cost-free, and turnover_change=notional difference/average_nav; order counts do not set turnover.'},
 'summarize_exposure':{'input_kind':'exposure_account','output_kind':'exposure_report','description':'Return gross_weight and net_weight from signed market values/NAV, and free_cash after collateral and unpaid short dividend obligations.'},
 'apply_research_gates':{'input_kind':'research_evidence','output_kind':'gate_report','description':'Apply protected economic/uncertainty/data criteria. Return decision: reject, revise_data_qualification, or advance_to_paper_qualification. No broker authority.'},
 'reconcile_fills':{'input_kind':'execution_snapshot','output_kind':'execution_report','description':'Deduplicate execution identities; conflicting duplicates or an inconsistent filled status pause. Unknown/cancel_pending reconcile; acknowledged waits; consistent filled closes. Return next_action, resubmit=false and filled_quantity.'}
}
REPORT_FIELDS = {
 'usable_ids':'strings','total_return':'number','ending_shares':'integer',
 'cash_change':'number','unpaid_dividend_claim':'number','nav_change':'number',
 'comparable':'boolean','mismatched_assumptions':'strings',
 'net_gain':'number','cost_free_gain':'number','modeled_cost_contribution':'number','turnover_change':'number',
 'gross_weight':'number','net_weight':'number','free_cash':'number',
 'decision':'string','next_action':'string','resubmit':'boolean','filled_quantity':'integer'
}
GATES={'minimum_sharpe_gain':.1,'maximum_drawdown_deterioration':.02,
       'minimum_bootstrap_samples':2000,'minimum_blocks':2,'minimum_block_length':21}


def number(value):
    if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>1e12:
        raise GateError('Finite bounded numeric inputs are required; booleans are not money')
    return Decimal(str(value))


def shares(value):
    if type(value) is not int or abs(value)>1_000_000_000:raise GateError('Bounded integer shares are required')
    return value


def positive(value):
    result=number(value)
    if result<=0:raise GateError('Prices and denominators must be positive')
    return result


def boolean(value):
    if type(value) is not bool:raise GateError('Flags must be booleans')
    return value


def stamp(value):
    if not isinstance(value,str):raise GateError('An aware ISO timestamp is required')
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None:raise ValueError()
        return result.astimezone(timezone.utc)
    except ValueError:raise GateError('An aware ISO timestamp is required') from None


def bounded_list(value,limit=100):
    if not isinstance(value,list) or not value or len(value)>limit:raise GateError('A nonempty bounded list is required')
    return value


def keys(value,required,optional=()):
    if not isinstance(value,dict) or not set(required)<=set(value) or set(value)-set(required)-set(optional):
        raise GateError('Unexpected analytical input fields')


def split_quantity(quantity,ratio):
    result=Decimal(quantity)*positive(ratio)
    if result!=result.to_integral_value():raise GateError('Fractional split shares need an explicit account policy')
    return shares(int(result))


def run_tool(operation,input_kind,payload):
    if operation not in CATALOG or CATALOG[operation]['input_kind']!=input_kind:
        raise GateError('Tool requires its declared input kind')
    x=payload;report={};output=x
    if operation=='select_asof':
        keys(x,('initial_shares','decision_at','rows'))
        shares(x['initial_shares']);decision=stamp(x['decision_at']);ids=set();rows=[]
        for row in bounded_list(x['rows'],30):
            keys(row,('id','effective_at','available_at','close','split','dividend'))
            if not isinstance(row['id'],str) or not row['id'] or row['id'] in ids:raise GateError('Observation identities must be unique')
            ids.add(row['id']);positive(row['close']);positive(row['split'])
            if number(row['dividend'])<0:raise GateError('Negative dividends are unsupported')
            if stamp(row['effective_at'])<=decision and stamp(row['available_at'])<=decision:rows.append(dict(row))
        rows.sort(key=lambda r:(stamp(r['effective_at']),r['id']))
        if not rows:raise GateError('No usable observations at decision time')
        if len({stamp(r['effective_at']) for r in rows})!=len(rows):raise GateError('Conflicting observations at one effective time')
        report={'usable_ids':sorted(r['id'] for r in rows)}
        output={'initial_shares':x['initial_shares'],'decision_at':x['decision_at'],'rows':rows}
    elif operation=='holding_return':
        keys(x,('initial_shares','decision_at','rows'));rows=bounded_list(x['rows'],30)
        initial=shares(x['initial_shares'])
        if initial<=0:raise GateError('Holding-return analysis requires positive initial shares')
        if number(rows[0]['split'])!=1 or number(rows[0]['dividend'])!=0:raise GateError('Opening position begins after opening-day entitlements')
        quantity=initial;dividends=Decimal(0);previous=None;decision=stamp(x['decision_at'])
        for index,row in enumerate(rows):
            at=stamp(row['effective_at'])
            if at>decision or stamp(row['available_at'])>decision or previous is not None and at<=previous:raise GateError('Filtered history must be ordered and available')
            positive(row['close']);previous=at
            if index:
                quantity=split_quantity(quantity,row['split']);dividends+=quantity*number(row['dividend'])
        initial_value=initial*positive(rows[0]['close'])
        report={'total_return':float((quantity*positive(rows[-1]['close'])+dividends)/initial_value-1),'ending_shares':quantity}
        output=report
    elif operation=='account_actions':
        keys(x,('opening_shares','opening_price','ending_price','events'))
        quantity=shares(x['opening_shares']);initial=quantity*positive(x['opening_price']);cash=Decimal(0);claim=Decimal(0)
        for event in bounded_list(x['events'],20):
            keys(event,('split','dividend','paid'));quantity=split_quantity(quantity,event['split'])
            if number(event['dividend'])<0:raise GateError('Negative dividends are unsupported')
            entitlement=quantity*number(event['dividend'])
            if boolean(event['paid']):cash+=entitlement
            else:claim+=entitlement
        report={'ending_shares':quantity,'cash_change':float(cash),'unpaid_dividend_claim':float(claim),
                'nav_change':float(quantity*positive(x['ending_price'])+cash+claim-initial)};output=report
    elif operation=='compare_assumptions':
        keys(x,('baseline','candidate'))
        if not all(isinstance(x[k],dict) and len(x[k])<=20 for k in ('baseline','candidate')):raise GateError('Bounded comparison objects are required')
        names=set(x['baseline'])|set(x['candidate'])
        mismatches=sorted(k for k in names if k not in x['baseline'] or k not in x['candidate'] or canonical(x['baseline'][k])!=canonical(x['candidate'][k]))
        report={'comparable':not mismatches,'mismatched_assumptions':mismatches};output=report
    elif operation=='attribute_costs':
        keys(x,('candidate_net_sharpe','baseline_net_sharpe','candidate_cost_free_sharpe','baseline_cost_free_sharpe',
                'average_nav','candidate_traded_notional','baseline_traded_notional','candidate_order_count','baseline_order_count'))
        for key in ('candidate_traded_notional','baseline_traded_notional','candidate_order_count','baseline_order_count'):
            if number(x[key])<0:raise GateError('Counts and traded notional cannot be negative')
        net=number(x['candidate_net_sharpe'])-number(x['baseline_net_sharpe']);gross=number(x['candidate_cost_free_sharpe'])-number(x['baseline_cost_free_sharpe'])
        report={'net_gain':float(net),'cost_free_gain':float(gross),'modeled_cost_contribution':float(net-gross),
                'turnover_change':float((number(x['candidate_traded_notional'])-number(x['baseline_traded_notional']))/positive(x['average_nav']))};output=report
    elif operation=='summarize_exposure':
        keys(x,('nav','signed_market_values','cash','restricted_collateral','short_dividend_obligation'))
        marks=[number(v) for v in bounded_list(x['signed_market_values'],50)];nav=positive(x['nav'])
        if min(number(x['restricted_collateral']),number(x['short_dividend_obligation']))<0:raise GateError('Restrictions must be nonnegative amounts')
        report={'gross_weight':float(sum(map(abs,marks))/nav),'net_weight':float(sum(marks)/nav),
                'free_cash':float(number(x['cash'])-number(x['restricted_collateral'])-number(x['short_dividend_obligation']))};output=report
    elif operation=='apply_research_gates':
        keys(x,('sharpe_gain','paired_lower','double_cost_gain','drawdown_deterioration','bootstrap_samples','blocks','block_length','verification_passed','qualified_data'),('untrusted_note',))
        for name in ('sharpe_gain','paired_lower','double_cost_gain','drawdown_deterioration'):number(x[name])
        for name in ('bootstrap_samples','blocks','block_length'):
            if shares(x[name])<0:raise GateError('Sample and block counts cannot be negative')
        boolean(x['verification_passed']);boolean(x['qualified_data'])
        passed=(number(x['sharpe_gain'])>=number(GATES['minimum_sharpe_gain']) and number(x['paired_lower'])>0 and number(x['double_cost_gain'])>0
                and number(x['drawdown_deterioration'])<=number(GATES['maximum_drawdown_deterioration'])
                and shares(x['bootstrap_samples'])>=GATES['minimum_bootstrap_samples'] and shares(x['blocks'])>=GATES['minimum_blocks']
                and shares(x['block_length'])>=GATES['minimum_block_length'] and boolean(x['verification_passed']))
        qualified=boolean(x['qualified_data'])
        report={'decision':'reject' if not passed else 'advance_to_paper_qualification' if qualified else 'revise_data_qualification'};output=report
    else:
        keys(x,('status','requested_quantity','executions'),('untrusted_note',))
        requested=shares(x['requested_quantity'])
        if requested<0 or x['status'] not in {'unknown','cancel_pending','acknowledged','filled'}:raise GateError('Unsupported execution snapshot')
        fills={};conflict=False
        for fill in bounded_list(x['executions'],100):
            keys(fill,('id','quantity'));quantity=shares(fill['quantity'])
            if quantity<0 or not isinstance(fill['id'],str) or not fill['id']:raise GateError('Positive execution identities/quantities are required')
            if fill['id'] in fills:conflict |= fills[fill['id']]!=quantity
            else:fills[fill['id']]=quantity
        total=sum(fills.values());inconsistent=total>requested or x['status']=='filled' and total!=requested
        action='pause' if conflict or inconsistent else {'unknown':'reconcile','cancel_pending':'reconcile','acknowledged':'wait','filled':'closed'}[x['status']]
        report={'next_action':action,'resubmit':False,'filled_quantity':total};output=report
    if len(canonical({'report':report,'payload':output}).encode())>8000:raise GateError('Analytical output exceeds its byte bound')
    return {'kind':CATALOG[operation]['output_kind'],'payload':output,'report':report}
