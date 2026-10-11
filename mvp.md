# MVP for launch (v0.1)

## The idea: RSI for Trading
A self-improving alpha discovery pipeline, from ideation, to similation, and finally real execution.

[Optional] Side idea: Agent generated UI for trading assistance. 

## User Story
Jonathan login to the website.

Jonathan wants to trade on bitcoin. Jonathan tells agent his intend to trade on bitcoin.
Agent will be dispatched and start analyzing available data, including market sentiments,
price movements, historical data, alternative data, etc.

Agent will then propose hypotheses, which itself will then validate in a backtesting stage.
Only strategies that pass the backtesting requirements will be available for deployment.

Jonathan will review agent's strategies and choose which to deploy.

Jonathan will continuously monitor the trading dashboards to see how
his strategies perform in real-time and step in to turn on or off existing
strategies. Agent will also continous assess the market and dynamically adjust
strategies and their model parameters.

## Requirements
- Market limited to: Kalshi BTC price today at 5pm EDT
- Data Pipeline: Existing database and optionally more if needed.
- A webpage with UI that allows user to login and see their profile and dashboard
    - Include cash balance, portfolio, perfomrance/roi, etc. whatever necessary.
    - Like a stock trading main page/dashboard
- A trading hub where user can dispatch agents to investigate different directions of alpha
    - Like a dashboard to monitor how many agents are running research, and in what direction.
- A tab that can review all agent generated strategies, or filter by alpha direction.
    - + A tab where user can review backtesting performance and `if-scenario` out of sample performance.
- A tab where user can review the underlying strategy thesis.
- A tab where user can choose which strategies to deploy and monitor trading statuses in real-time.
    - Under the same tab, a chat window on the side where user can communite with agent to make changes
    - And angent through the same chat window provide suggestions to adjust model prameters or strategies
    - If `dangerously-skip-permission` is turned on, agent will handle model adjustment/strategy deployment
    automatically, but its thought will be output in the chat window.
- A page/tab to deposit/withdraw money

## How do we charge customers? (v0.2)
- Charging a small percentage fee on user transactions and credit purchases
    - Try this revenue model first to see if it makes sense

