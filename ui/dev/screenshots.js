//
// Copyright (C) 2026 Dan Brown
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Takes the screenshots of docs/USER-GUIDE.md from the UI harness. See
// "Screenshots" in ui/dev/README.md. Runs in the Playwright image; HARNESS is
// the harness URL as seen from the container, OUT the directory the PNG files
// are written to. Adapted from ns8-dnshelper's ui/dev/screenshots.js.
const { chromium } = require("playwright-core");

const BASE = process.env.HARNESS || "http://host.docker.internal:8098/";
const OUT = process.env.OUT || "/out";
const BAR = 30; // the harness's own top bar, left out of the pictures
const WIDTH = 800;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: WIDTH, height: 512 + BAR },
    deviceScaleFactor: 1,
    locale: process.env.LOCALE || "en-US",
  });
  page.on("pageerror", (e) => console.log("PAGE ERROR", e.message));
  await page.goto(BASE);
  await sleep(3000);
  const frame = () => page.frames().find((f) => f.url().includes("/app/"));
  const resize = (height, width = WIDTH) => page.setViewportSize({ width, height: height + BAR });
  const shot = async (name) => {
    await sleep(900);
    await page.locator("iframe").screenshot({ path: `${OUT}/${name}.png` });
    console.log("shot", name);
  };
  // run fn(root, findBy, sleep, nav, d, arg) inside the app frame
  const run = (fn, arg, ms = 30000) => Promise.race([
    new Promise((_, rej) => setTimeout(() => rej(new Error("step timed out: " + fn.toString().slice(0, 120))), ms)),
    frame().evaluate(
      async ({ src, arg }) => {
        const d = document;
        const root = d.querySelector("#ns8-app").__vue__;
        const findBy = (v, n) => {
          if (v.$options.name === n) return v;
          for (const c of v.$children) {
            const x = findBy(c, n);
            if (x) return x;
          }
        };
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
        const nav = async (index) => {
          // by position in the side menu (Status, Domains, Settings, About), so that it
          // works in any language
          [...d.querySelectorAll(".bx--side-nav__link")][index].click();
          await sleep(2000);
        };
        // eslint-disable-next-line no-new-func
        return await new Function("root", "findBy", "sleep", "nav", "d", "arg", `return (${src})(root, findBy, sleep, nav, d, arg)`)(
          root, findBy, sleep, nav, d, arg
        );
      },
      { src: fn.toString(), arg }
    )]);
  const STATUS = 0, DOMAINS = 1, SETTINGS = 2;
  const openOnRow = (method, domain) => run(async (root, findBy, sleep, nav, d, arg) => {
    const page = findBy(root, "Domains");
    page[arg.method](page.rows.find((r) => r.domain === arg.domain));
    await sleep(2500);
    // Opening focuses the primary button, which scrolls a tall dialog to its end.
    d.activeElement.blur();
    d.querySelectorAll(".bx--modal.is-visible, .bx--modal.is-visible .bx--modal-container, .bx--modal.is-visible .bx--modal-content")
      .forEach((el) => { el.scrollTop = 0; });
    await sleep(300);
  }, { method, domain });
  const closeDialogs = () => run(async (root, findBy, sleep) => {
    const page = findBy(root, "Domains");
    page.isDnsStatusShown = page.isProfileLinkShown = page.isDomainSettingsShown = false;
    await sleep(800);
  });

  // ---- Status
  await run(async (root, findBy, sleep, nav) => { await nav(0); }, STATUS);
  await shot("status");

  // ---- Domains and its dialogs
  await run(async (root, findBy, sleep, nav) => { await nav(1); }, DOMAINS);
  await shot("domains");
  // The large dialogs at the width where they show as a window over the page.
  await resize(640, 1056);
  await openOnRow("showDnsStatus", "example.com");
  await shot("dns-status");
  await closeDialogs();
  await resize(1080, 1056);
  await openOnRow("showDnsStatus", "example.net");
  await shot("dns-status-not-permitted");
  await closeDialogs();
  await resize(900, 1056);
  await openOnRow("showProfileLink", "example.com");
  await shot("profile-link");
  await closeDialogs();
  await resize(720);
  await openOnRow("showDomainSettings", "example.org");
  await shot("domain-settings");
  await closeDialogs();

  // ---- Settings: the top of the page, then the bottom
  await resize(512);
  await run(async (root, findBy, sleep, nav) => { await nav(2); await sleep(1500); }, SETTINGS);
  await shot("settings");
  // From "Defaults for all domains" to the end of the page.
  await resize(880);
  await run(async (root, findBy, sleep, nav, d) => {
    const heading = [...d.querySelectorAll("h4")].pop();
    d.scrollingElement.scrollTo(0, heading.getBoundingClientRect().top + d.scrollingElement.scrollTop - 24);
    await sleep(500);
  });
  await shot("settings-groupware");

  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
