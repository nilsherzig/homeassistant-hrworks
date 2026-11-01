// Enter working times through the portal's "AI assistance" dialog: send the prompt, read the
// "Check Input" proposal, fix each row's working-time type, verify the proposal against the rows
// Python expects and (only for a non-dry request) save it. With dry_run nothing is saved: the
// proposal is read and the dialog cancelled. Existing entries are never touched; a proposal row
// the portal flags as already existing aborts the save.
async ({ page, args }, H) => {
  const { PortalError, normalize, settle } = H;
  await H.ensureViewport(page);
  const { prompt, rows: expected, dry_run: dryRun } = args;
  const button = (scope, pattern) => scope.getByRole('button', { name: pattern });
  const CREATE = /^\s*(Create|Erstellen)\s*$/;
  const SAVE = /^\s*(Save|Speichern)\s*$/;
  const CANCEL = /^\s*(Cancel|Abbrechen)\s*$/;
  const ROW = /(\d{2})\.(\d{2})\.(\d{2}|\d{4})\s+(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})/;
  const EXISTS = /already|bereits|exists|vorhanden/i;
  const key = (day, start, end) => `${day} ${start}-${end}`;
  const pad = value => value.padStart(2, '0');

  await H.navigate(page, 'working-times');
  const trigger = page.locator('.hrw-me-ai-assistant-button:visible').first();
  if (!await trigger.count()) throw new PortalError('portal_changed');
  await trigger.click();
  const dialog = page.locator('[role=dialog].show');
  await dialog.waitFor({ state: 'visible' });
  const box = dialog.locator('textarea');
  if (await box.count() !== 1) throw new PortalError('portal_changed');

  const leave = async () => {
    const cancel = button(dialog, CANCEL);
    if (await cancel.count()) await cancel.first().click().catch(() => {});
    await settle(page).catch(() => {});
  };

  try {
    await box.fill(prompt);
    await button(dialog, CREATE).click();
    const forms = dialog.locator('form').filter({ has: page.locator('select') });
    const deadline = Date.now() + 90000;
    while (!await forms.count()) {
      if (Date.now() > deadline) throw new PortalError('proposal_mismatch');
      await H.sleep(500);
    }
    await settle(page);

    const proposal = [];
    for (const form of await forms.all()) {
      const text = (await form.innerText()).replace(/\s+/g, ' ');
      const match = ROW.exec(text);
      if (!match) throw new PortalError('portal_changed');
      const [, d, m, y, h1, m1, h2, m2] = match;
      const day = `${y.length === 2 ? 2000 + Number(y) : y}-${m}-${d}`;
      proposal.push({
        form, day, start: `${pad(h1)}:${m1}`, end: `${pad(h2)}:${m2}`,
        exists: EXISTS.test(text.replace(ROW, '')),
      });
    }

    const wanted = new Map(expected.map(row => [key(row.date, row.start, row.end), row]));
    if (expected.length) {
      const seen = new Set(proposal.map(row => key(row.day, row.start, row.end)));
      if (proposal.length !== expected.length || seen.size !== proposal.length
          || [...wanted.keys()].some(k => !seen.has(k))) {
        throw new PortalError('proposal_mismatch');
      }
    }
    for (const row of proposal) {
      const want = wanted.get(key(row.day, row.start, row.end));
      const select = row.form.locator('select');
      if (want) {
        const labels = new Set(want.labels.map(normalize));
        const options = await select.locator('option').allTextContents();
        const chosen = options.find(label => labels.has(normalize(label)));
        if (chosen === undefined) throw new PortalError('writes_disabled');
        await select.selectOption({ label: chosen });
      }
      row.type = (await select.locator('option:checked').innerText()).trim();
    }
    await settle(page);
    const entries = proposal.map(({ day, start, end, type, exists }) => ({ date: day, start, end, type, exists }));
    if (dryRun) {
      await leave();
      return { saved: false, dry_run: true, entries };
    }
    if (entries.some(entry => entry.exists)) throw new PortalError('overlap');

    const save = button(dialog, SAVE);
    if (await save.count() !== 1) throw new PortalError('portal_changed');
    try {
      await save.click();
      await settle(page);
      const note = (await page.locator('.modal.show').last().innerText()).replace(/\s+/g, ' ');
      const created = (note.match(/Successfully created|Erfolgreich erstellt/gi) || []).length;
      if (created < entries.length) throw new PortalError('write_uncertain');
      for (const close of await page.locator('.modal.show').getByRole('button', { name: /^\s*(Close|Schlie(ß|ss)en|OK)\s*$/ }).all()) {
        await close.click().catch(() => {});
      }
      await page.reload({ waitUntil: 'commit', timeout: 45000 });
      for (const day of new Set(entries.map(entry => entry.date))) {
        const { entries: verified } = await H.workingDay(page, day);
        for (const entry of entries.filter(e => e.date === day)) {
          const labels = new Set(wanted.size
            ? wanted.get(key(day, entry.start, entry.end)).labels.map(normalize)
            : [normalize(entry.type)]);
          if (!verified.some(e => e.start === entry.start && e.end === entry.end
              && labels.has(normalize(e.type || '')))) {
            throw new PortalError('write_uncertain');
          }
        }
      }
    } catch {
      throw new PortalError('write_uncertain');
    }
    return { saved: true, dry_run: false, entries };
  } catch (err) {
    // Before Save was clicked nothing is stored: close the dialog and report.
    if (!dryRun && err.code === 'write_uncertain') throw err;
    await leave();
    throw err;
  }
}
