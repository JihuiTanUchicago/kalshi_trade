/* Tau's Terms of Service and Privacy Policy pages, viewable signed in or out (only Tau has them: boot.js
   serves /terms and /privacy in Tau for everyone). Fetched on first use (pageLoad in app.js), which hands
   this function what the bundle shares with its page files (shared()); the router calls the views it returns. */
window.TauPage('legal', (T) => {
  'use strict';
  const {api, clearTimers, ICON, root, S} = T;

  // ---------- public legal pages (viewable signed in OR out) ----------
  const LEGAL_CONTACT = 'tanjihui@tau-trading.com';
  const LEGAL_UPDATED = 'October 20, 2026';
  const sec = (h, ...ps) => `<h2>${h}</h2>${ps.map((p) => `<p>${p}</p>`).join('')}`;
  function legalShell(title, bodyHtml) {
    clearTimers();
    document.body.classList.add('landing-body');
    // Links out of the legal pages load the app afresh: boot.js serves these pages in Tau for
    // everyone, so a Meridian user has to reload to get their own theme back.
    const away = S.me ? '<a class="legal-away" href="/" data-native>Dashboard</a>' : '<a class="legal-away" href="/signin" data-native>Sign in</a>';
    root.innerHTML = `<div class="legal-wrap">
      <header class="legal-top"><a class="lbrand" href="/" data-native>${ICON.mark}<span>Tau</span></a>
        <nav class="legal-nav"><a href="/terms">Terms</a><a href="/privacy">Privacy</a>${away}</nav></header>
      <main class="legal" id="main">
        <h1>${title}</h1><p class="legal-updated">Last updated ${LEGAL_UPDATED}</p>
        ${bodyHtml}
        <footer class="legal-foot"><a href="/terms">Terms of Service</a> ·\u00a0<a href="/privacy">Privacy Policy</a> ·\u00a0<span>© 2026 Tau</span></footer>
      </main></div>`;
    // Public pages skip the boot /api/me, so a signed-in reader was offered "Sign in". Ask quietly
    // (a 401 here never redirects) and point the link at the dashboard when there is a session.
    if (!S.me) api('/api/me').then((me) => {
      const a = root.querySelector('.legal-away');
      if (me && me.user && a) { a.setAttribute('href', '/'); a.textContent = 'Dashboard'; }
    }).catch(() => {});
  }
  async function viewTerms() {
    legalShell('Terms of Service',
      sec('1. Agreement', `By accessing or using Tau (the “Service”), you agree to these Terms of Service. If you do not agree, do not use the Service.`) +
      sec('2. What Tau is', `Tau is software that helps you research, backtest, and automate trading strategies for prediction markets offered by Kalshi. Tau can place trades in a Kalshi account you connect, using credentials you provide. Tau is a software tool — it is not a broker-dealer, exchange, investment adviser, or fiduciary, and it does not hold your funds.`) +
      sec('3. Not financial advice', `Tau’s research, backtests, scores, and generated strategies are informational only. They are not investment, financial, legal, or tax advice, and are not a recommendation to enter into any trade. Backtested and simulated results are hypothetical and do not guarantee future performance. All trading decisions are your own and your sole responsibility.`) +
      sec('4. Eligibility', `You must be at least 18 years old and able to form a binding contract, and you may use the Service only where trading on prediction markets is lawful for you. You are responsible for complying with Kalshi’s terms and all laws that apply to you.`) +
      sec('5. Your account', `You sign in with Google. You are responsible for keeping your account secure and for all activity under it. Live trading uses your own Kalshi API credentials, which you choose to provide; Tau places trades only for strategies you deploy and never takes custody of your funds.`) +
      sec('6. Trading risk', `Trading on prediction markets involves substantial risk, including the total loss of the funds you commit. Only trade with money you can afford to lose. Paper and demo modes are simulated and involve no real money.`) +
      sec('7. Fees and billing', `Some features may require paid credits. Where paid features are enabled, you authorize charges through our payment processor (Stripe) for the credits or usage described in the app, and credits are consumed as the agent performs work for you. Pricing may change, and any changes will be reflected in the app.`) +
      sec('8. Acceptable use', `You agree not to use the Service unlawfully; not to abuse, reverse-engineer, disrupt, or overload it; and not to use it to violate the rules of Kalshi or any exchange, venue, or third party.`) +
      sec('9. Intellectual property', `Tau and its software, content, and branding are owned by its operator; you receive a limited, non-exclusive, non-transferable license to use the Service. Content and inputs you submit remain yours, and you grant us a license to process them solely to operate and improve the Service.`) +
      sec('10. Disclaimers', `The Service is provided “as is” and “as available,” without warranties of any kind, express or implied, including merchantability, fitness for a particular purpose, availability, accuracy, or profitability.`) +
      sec('11. Limitation of liability', `To the maximum extent permitted by law, the operator of Tau is not liable for any trading losses or for any indirect, incidental, special, consequential, or punitive damages arising from your use of the Service. Our total liability for any claim is limited to the amount you paid us for the Service in the three months before the claim.`) +
      sec('12. Termination', `We may suspend or terminate access for any violation of these Terms or to protect the Service or its users. You may stop using the Service at any time.`) +
      sec('13. Changes', `We may update these Terms from time to time. Material changes will be posted here with a new “last updated” date, and your continued use of the Service means you accept the updated Terms.`) +
      sec('14. Contact', `Questions about these Terms: <a href="mailto:${LEGAL_CONTACT}">${LEGAL_CONTACT}</a>.`));
  }
  async function viewPrivacy() {
    legalShell('Privacy Policy',
      sec('Overview', `This policy explains what information Tau collects, how we use it, and the choices you have. By using Tau you agree to this policy.`) +
      sec('Information we collect', `<strong>Account information</strong> — your name and email address from Google sign-in. <strong>Usage data</strong> — the research sessions, strategies, settings, and interactions you create in the app. <strong>Payment information</strong> — processed by our payment provider (Stripe); we do not store your full card number. <strong>Trading credentials</strong> — if you connect live trading, your Kalshi API key, stored encrypted. <strong>Technical data</strong> — standard logs such as IP address and browser type.`) +
      sec('How we use it', `To provide and operate the Service; to run your research and backtests; to process billing; to secure, maintain, and improve the Service; and to communicate with you about your account.`) +
      sec('AI processing', `Your research inputs and prompts are processed by our AI provider (Anthropic, via Amazon Bedrock) to generate research and strategies. Please do not include sensitive personal information in research prompts.`) +
      sec('How we share it', `We do not sell your personal information. We share it only with the service providers that run Tau — Google (sign-in), Stripe (payments), Amazon Web Services (hosting), and Anthropic / Amazon Bedrock (AI) — and when required by law or to protect the Service and its users.`) +
      sec('Cookies and local storage', `We use a session cookie to keep you signed in and your browser’s local storage for preferences such as your theme. We do not use third-party advertising cookies.`) +
      sec('Data retention', `We keep your information while your account is active and for as long as needed to operate the Service and meet legal and security obligations.`) +
      sec('Security', `We protect sensitive credentials with encryption and apply reasonable safeguards. No method of storage or transmission is completely secure, so we cannot guarantee absolute security.`) +
      sec('Your choices', `You can access, correct, or delete your information by contacting us. You can disconnect live trading and sign out at any time.`) +
      sec('Children', `Tau is not directed to, and may not be used by, anyone under 18.`) +
      sec('Changes', `We may update this policy; we will post changes here with a new “last updated” date.`) +
      sec('Contact', `Questions about privacy or your data: <a href="mailto:${LEGAL_CONTACT}">${LEGAL_CONTACT}</a>.`));
  }

  return {viewTerms, viewPrivacy};
});
