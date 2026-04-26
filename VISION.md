<div style="max-width: 680px; font-family: var(--font-sans); color: var(--color-text-primary); line-height: 1.75; padding: 1.5rem 0;">

  <h1 style="font-size: 22px; font-weight: 500; margin: 0 0 0.5rem;">Vision of AutomatiQ</h1>

  <p style="margin: 0 0 1rem; color: var(--color-text-secondary); font-size: 15px;">
    Automatiq applies the philosophy of "breaking things apart and building them back up" to the modern web. Life is short, and I hate doing things the long way. Why waste hours on manual data entry when a 300-line Python script can do the exact same thing forever?
  </p>
  <p style="margin: 0 0 2rem; color: var(--color-text-secondary); font-size: 15px;">
    With AI, automating these tasks should only take a minute. But developing that extraction script remains a complex challenge.
  </p>

  <h2 style="font-size: 16px; font-weight: 500; margin: 0 0 0.5rem;">The browser dependency</h2>
  <p style="margin: 0 0 1rem; color: var(--color-text-secondary); font-size: 15px;">
    Right now, the internet rides on two things to stop automation: CAPTCHAs and browser fingerprinting. The industry's accepted solution to this is terrible; they just run a full headless Chromium browser for everything, which is bloated, slow, and wastes compute.
  </p>
  <p style="margin: 0 0 2.5rem; color: var(--color-text-secondary); font-size: 15px;">
    Chrome is used in Automatiq's recording phase for one reason only: to watch, learn, and record what happens. It is a one-time process. A browser is a tool for humans to view the web; it should not be the engine we rely on to run a script in the background forever.
  </p>

  <h2 style="font-size: 18px; font-weight: 500; margin: 0 0 1.25rem;">How Automatiq works</h2>
  <p style="margin: 0 0 1.5rem; color: var(--color-text-secondary); font-size: 15px;">
    AI should act as a developer's partner, producing tools that make things faster. Automatiq operates in two distinct phases.
  </p>

  <div style="border-left: 2px solid var(--color-border-secondary); padding-left: 1.25rem; margin-bottom: 1.75rem;">
    <h3 style="font-size: 15px; font-weight: 500; margin: 0 0 0.5rem;">Recorder phase</h3>
    <p style="margin: 0; color: var(--color-text-secondary); font-size: 15px;">
      You start with a Chrome browser where you interact with any website normally. In the background, Automatiq records every click, keystroke, and network request — while also capturing a video of your session. This video is broken into segments, associated with specific actions, and fed to a Vision-Language Model (VLM) for a high-level summary. The recorder then outputs a folder containing an environment designed specifically for the agent, holding all the browser information it will ever need.
    </p>
  </div>

  <div style="border-left: 2px solid var(--color-border-secondary); padding-left: 1.25rem; margin-bottom: 2.5rem;">
    <h3 style="font-size: 15px; font-weight: 500; margin: 0 0 0.5rem;">Agent phase</h3>
    <p style="margin: 0 0 0.75rem; color: var(--color-text-secondary); font-size: 15px;">
      Why not use something like Claude Code or OpenCode? Those are designed as coding agents, meant to work with clean code in a local directory. Here, we need the AI to get its hands dirty with complex, broken, and unformatted data from decade-old websites.
    </p>
    <p style="margin: 0; color: var(--color-text-secondary); font-size: 15px;">
      Coding agents write more than they read, but a reverse-engineering agent needs to read more than it writes. Automatiq's agent is equipped with a standard IPython environment where shell commands and Python can be written side-by-side to reduce complexity. It also includes its own copy of BusyBox for Windows, ripgrep, jq, and sd to explore unstructured data.
    </p>
  </div>

  <div style="background: var(--color-background-secondary); border-radius: var(--border-radius-lg); padding: 1.25rem 1.5rem; margin-bottom: 2.5rem;">
    <h3 style="font-size: 15px; font-weight: 500; margin: 0 0 0.5rem;">The goal</h3>
    <p style="margin: 0; color: var(--color-text-secondary); font-size: 15px;">
      Automatiq is built to break a website's security model apart, analyze the raw network requests with AI, and build it back up into a clean, browser-less script that serves the user. Just like people say they can build anything with Claude Code, Automatiq is designed to give you the ability to scrape or automate anything on the web — entirely without the bloat.
    </p>
  </div>

  <h2 style="font-size: 18px; font-weight: 500; margin: 0 0 1.5rem;">The Roadmap</h2>

  <div style="display: flex; flex-direction: column; gap: 1.25rem; margin-bottom: 2.5rem;">
    <div style="background: var(--color-background-primary); border: 0.5px solid var(--color-border-tertiary); border-radius: var(--border-radius-lg); padding: 1.25rem 1.5rem;">
      <h3 style="font-size: 15px; font-weight: 500; margin: 0 0 0.5rem;">JavaScript virtual machine</h3>
      <p style="margin: 0; color: var(--color-text-secondary); font-size: 15px;">
        Many modern sites use obfuscated JavaScript to generate request credentials or cryptographic tokens. Instead of firing up Chromium to run this, Automatiq will integrate a small JS VM; exactly how tools like <code style="font-family: var(--font-mono); font-size: 13px; background: var(--color-background-secondary); padding: 2px 5px; border-radius: 4px;">yt-dlp</code> run YouTube's JS natively to generate request credentials. The AI agent will extract the specific JavaScript it needs, attach the VM as a Python module, and use it in the final script to generate required tokens.
      </p>
    </div>
    <div style="background: var(--color-background-primary); border: 0.5px solid var(--color-border-tertiary); border-radius: var(--border-radius-lg); padding: 1.25rem 1.5rem;">
      <h3 style="font-size: 15px; font-weight: 500; margin: 0 0 0.5rem;">Surgical browser usage</h3>
      <p style="margin: 0; color: var(--color-text-secondary); font-size: 15px;">
        If a site's fingerprinting is truly unbreakable, the generated script still shouldn't run a headless browser for the entire process. The AI will learn to spin up Chrome just for the exact request that needs it, grab the clearance token, kill the browser, and handle the rest in pure Python.
      </p>
    </div>
    <div style="background: var(--color-background-primary); border: 0.5px solid var(--color-border-tertiary); border-radius: var(--border-radius-lg); padding: 1.25rem 1.5rem;">
      <h3 style="font-size: 15px; font-weight: 500; margin: 0 0 0.5rem;">Isolated technique plugins</h3>
      <p style="margin: 0; color: var(--color-text-secondary); font-size: 15px;">
        To bypass complex defenses like Cloudflare or advanced CAPTCHAs, Automatiq will introduce a plugin system. These won't be "Instagram scrapers" or "LinkedIn bots", we have no interest in building a marketplace for specific site scrapers. Instead, these plugins will be isolated techniques, similar to cybersecurity skills like TLS spoofing, JS debugging hooks, or CAPTCHA routing. They'll give the AI the exact tools it needs to break a specific defense and rebuild the script without cluttering the core engine.
      </p>
    </div>
  </div>
    <div style="background: var(--color-background-secondary); border-radius: var(--border-radius-lg); padding: 1.25rem 1.5rem; margin-top: 1.25rem;">
    <h2 style="margin: 0 0 0.5rem; color: var(--color-text-primary); font-size: 15px; font-weight: 500;">AutomatiQ is a Community Project</h2>
    <p style="margin: 0; color: var(--color-text-secondary); font-size: 15px;">
      We break the web down so we can automate it efficiently, making development faster and easier for everyone. Contributions of any kind are welcome, and thanks for being here.
    </p>
  </div>

</div>
