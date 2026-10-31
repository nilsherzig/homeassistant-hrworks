// Enter the authenticator code in the portal tab login.js left open (run with `tab`). A
// rejected code keeps the tab for another try; success keeps it as the logged-in portal tab.
async ({ page, args }, H) => {
  await H.ensureViewport(page);
  return await H.mfa(page, args.code);
}
