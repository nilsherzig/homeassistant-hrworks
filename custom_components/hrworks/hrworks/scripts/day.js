// The entries and metrics of one day.
async ({ page, args }, H) => {
  await H.ensureViewport(page);
  return await H.workingDay(page, args.date);
}
