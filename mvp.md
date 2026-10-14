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

## UI
- Dashboard: A webpage with UI that allows user to login and see their profile and dashboard
    - Include cash balance, portfolio, perfomrance/roi, etc. whatever necessary.
    - Like a stock trading main page/dashboard
- Strategy: I want to bring research + strategies into one page, each is indicated by a status sign 
    - Each "Agent Sessions" instance is displayed as a card
    - Tab shows "Agent Sessions". 3 states:
        - Researching
        - Finalized strategy pending review
        - Deployed
    - Clicking into each "Agent Session", it shows 
        - backtesting performance and `if-scenario` out of sample performance
        - the underlying strategy thesis
- Position: shows all the user's open positions, as well as the deployed strategies
    - Keep the current "Deploy" tab, and clean the UI as well as show positions (integrating positions with deployments)
- Community: keep as is, I like the idea of social trading
- Account: links to the users account details, fundings, and other connected accounts

## THOUGHTS
### Must-have Features
- Our simulations do not consider the fact that Kalshi has a dev environment for testing
    - Maybe we should use that for an enhanced dev testing environment
- We should adapt OpenRouter's revenue model for early adoptions; easiest way to persuade
and justify our services.

### Interesting Features
- Make agent pipeline that allows the user to collect data itself
    - Maybe once collected, it can be shared across all users
    - Maybe we can charge also by storage cost? (i.e. how many data they use/subscribe to)
- Social/Interactive Elements
    - Maybe people can see their friends' holdings
    - Maybe people can sell others their alpha with a margin
    - Allow people to start a "Hedge Fund" on the platform where other people can put money in
- Agent generated UI for assited manual trading
    - UI is also a big part of trading business!
- Notification when RSI found something new.
- A "simulation lab" for agent-driven trading strategies. Adding super detailed features
for trading firms/teams that only focus on agent-driven strategies.
    - Specify number of swarms + number of agents in swarm
    - Specify direction/asset class
    - Specify how to cross contaminate
    - Specify competitions/rl rewards, etc.
    - Specify data
- Integrate with a person's paycheck.
    - A percentage of the paycheck will contribute to investment on this platform
        - Lean towards the "AI-native Hedge Fund" narrative. This sounds like we will
        want to manage the money for our customers
- A credit/debit card for customers to easily use their money deposited on our platform.
    - Automatically sell some positions to cover their expenses.
- Centralized dashboard to control what features we should enable, and to what user

### Open Souce?
- Software is cheap. We could probably open source our code. Our moats:
    - We build data collection automation pipeline. And we enable users who need
those data to collect and help us grow our datasets.
    - Our underlying execution service is not open sourced. Any edge we can win here?
    - (Jonathan supp): agent runtime, platform, data, trading execution and potentially 
    even prime services (leverage, borrowing, currency conversion, etc.)
    - We can post-train models using our in-house data for:
        - A jev like model that replaces traditional ML and only output "buy"/"sell"...?
            - TBH I don't even know what this means
            - (Jonathan supp): this makes sense and we can make it into a classifier-type model like Jev.
              The model outputs buy/sell/hold, with confidence level like what Jev does. Agree this is a
              great direction that we can go post-traction (and when we have the compute for post-train) 

## Traction
- Sell product EARLY. How to ask friends/strangers to try out product
whether making them willing to pay?
    - Maybe not subscription. Also subscription doesn't make sense because
    this won't generate a lot of revenue in the long run.
        - Option A: charge them when they deploy a strategy after backtesting
            - A small percentage cut of their profit
            - Or a fixed price "deployment to production" price
        - Option B: charge them when they need additional data
        - Option C: charge them when they need credits to fund their agents
            - e.g. a margin on top of their API credits
            - a quick thought but might be over-doing:
                - They plug in their exising API key, though we can't just tell OpenAI
                to give us some margins. What we can do, is that when user uses the API,
                we add a little embedding that routes someone else's request, so that
                we are cashing out the user's credit by using the user's credit and fulfills
                someone else's totally irrelevant requests.
                    - Bad, for rate limiting reasons, and bloating a user's bill
                    - (jonathan supp): feels a bit tricky and dangerous 
        - Option D: charge them for premium execution service
            - This can also let us make our product open source.
        - Option E: our own prop trading house run by our own TAU agents
    - (jonathan supp): Option A is the most optimal one at this stage imo

## Frictions found along the way.
- API keys are the bottleneck, not coding. A frictionless api-key-dependent development solution?
    - (jonathan supp) Agree. I cannot test what has been deployed at the moment because the API key is not available my end
- Codes become harder and harder to read with fast development. Maybe a visualization layer on top, so that users only
need to read code when they want to?
    - (jonathan supp) Yes my take is frontend should be as distraction-free as possible with only the necessary information presented
- User testing. Agent as a simulated user to test front end UIs.
- User testing. Agent as a simulated user to test front end UIs.
- computer agent to help me do things that previously I needed to manually do.
- New UI/interface, but agent has old knowledge -- there should be a product that
ensure agent-friendly user interface so that knowledge doesn't drift
