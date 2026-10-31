// The newest month's time account.
async ({ page, args }, H) => {
  await H.ensureViewport(page);
  return await H.account(page, args.year);
}
