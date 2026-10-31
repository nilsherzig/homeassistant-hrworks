// Drop the HR WORKS cookies of the browser profile.
async ({ context }, H) => {
  await context.clearCookies({ domain: /(^|\.)hrworks\.de$/ });
  return { logged_out: true };
}
