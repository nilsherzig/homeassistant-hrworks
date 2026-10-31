// Time account, leave and sickness lists and today's entries in one run, in one tab.
// The integration filters and merges the lists (see browser_daemon.py).
async ({ page, browser, args }, H) => {
  await H.ensureViewport(page);
  const timings = {};
  let mark = Date.now();
  const account = await H.account(page, args.year);
  timings.account = (Date.now() - mark) / 1000;
  mark = Date.now();
  const lists = [];
  for (const year of args.years) {
    for (const kind of args.kinds) {
      lists.push({ year, kind, ...await H.eventList(page, kind, year) });
    }
  }
  timings.events = (Date.now() - mark) / 1000;
  mark = Date.now();
  const today = await H.workingDay(page, args.today);
  timings.today = (Date.now() - mark) / 1000;
  const text = await page.locator('body').innerText();
  return {
    account,
    lists,
    today,
    clock: /\bClock in\b|\bEinstempeln\b/.test(text) ? 'in_available'
      : /\bClock out\b|\bAusstempeln\b/.test(text) ? 'out_available' : null,
    timings,
    browser_version: browser.version(),
  };
}
