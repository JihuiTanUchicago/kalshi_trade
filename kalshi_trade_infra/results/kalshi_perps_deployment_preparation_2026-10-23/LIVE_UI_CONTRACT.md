# Bitcoin perps live UI contract — initial manual IOC release

User selected actual money, each agent order explicitly confirmed by its owner, and Kalshi's native margin/leverage/exposure limits without extra Tau financial caps. Root owns service, server and shared-bundle mount integration. New standalone plugin mounts only on Funds. It never submits automatically, polls broker APIs automatically, or implies binary-market execution is enabled.

Plugin interface: window.TAU_PERPS_LIVE.mount(host, {api, proposalId}); api(path) performs existing authenticated GET; api(path,body) performs existing CSRF-protected POST. host is private to the component. proposalId is optional positive integer from the Funds query string after the user clicks Review live order in chat. Use stale-mount/generation guards.

All paths under /api/kalshi/perps/live:
- GET / -> overview.
- POST /policy {enabled:boolean, acknowledge_real_money:true only when enabling, expected_version:integer} -> {policy}. No order is sent by this operation.
- POST /orders {request_key:8..80 safe UUID-like string,side:'bid'|'ask',count:whole-positive-contract string,price:positive decimal USD PER CONTRACT string,reduce_only:boolean} -> {order}. This is preview only.
- POST /proposals/{id}/preview {request_key:string} -> {order}. The server takes immutable proposal details; caller cannot change them. Preview only.
- POST /orders/{id}/submit {confirmed:true,expected_version:integer,request_hash:64hex} -> {order}. Only the user's explicit Confirm live order button invokes this. On an uncertain outcome, offer Check status; never retry/mint another submission automatically.
- POST /orders/{id}/refresh {} -> {order}. Read/reconcile only.
- POST /orders/{id}/cancel {confirmed:true,expected_version:integer,request_hash:64hex} -> {order}. Cancel this owned intent/remainder only, never account-wide.

Overview shape:
{enabled:boolean,environment:'production',policy:{enabled:boolean,version:integer,manual_confirmation_required:true,risk_mode:'kalshi_limits'},connected:boolean,eligible:boolean,account:null|{account_equity,available_balance,initial_margin,maintenance_margin,settled_funds:string},risk:null|{account_leverage,total_position_notional:string},market:null|{ticker,title,contract_multiplier,tick_size:string,market_version:integer},quote:null|{bid,ask:string,retrieved_at:string},fees:null|{taker_rate:string},positions:[{ticker,position:string}],orders:[Order],message?:fixed string,error_code?:fixed string}. All numbers involving money/quantity are decimal strings; absent account/risk/quote is unknown, never $0. No API keys, signatures, account identifiers or raw provider bodies enter this UI.

Order shape:
{id:integer,environment:'production',client_order_id:string,source:'user'|'agent',status:string,version:integer,request_hash:64hex,request:{ticker,side,count,price,time_in_force:'immediate_or_cancel',reduce_only:boolean},filled_count:string,remaining_count:null|string,filled_avg_price:null|string,total_fees:null|string,created_at:string,expires_at:string,preview:{contract_multiplier,btc_quantity,notional_usd,estimated_fee_usd,taker_fee_rate,account_equity,available_balance,account_leverage:string,quoted_at:string},error_code:null|bounded code}.

UI: inherit both themes, compact Funds section; show live account/eligibility and broker margin limits, per-user enable, whole contracts and USD-per-contract limit form, reduce-only choice, preview with exact side/count/BTC units/limit/notional/estimated fee + fresh available margin/current leverage, then one explicit Confirm live order action. Label IOC as unfilled quantity canceled, distinguish filled/partial/unfilled/unknown. Connected=false links existing Settings for the user's own Kalshi key. Eligible=false links official Kalshi perps access documentation. Do not request a key inside chat or put secrets into DOM/storage. Do not add arbitrary financial caps or leverage sliders; native API has no leverage field. Initial order entry is always a bounded price limit. Existing positions/other orders are shown or kept intact, never adopted/canceled silently.

Status vocabulary comes from repository/service; tolerateunknown fixed strings as plain text (escape). Any positive-fill economics not yet confirmed remain unavailable. No synthetic P&L or practice ledger. Review-only generic chat proposals cannot bypass the separate exact-order confirmation.
