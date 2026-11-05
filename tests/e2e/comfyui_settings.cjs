// Opens ComfyUI's settings in a headless Chrome for Testing and checks the SteadyRouter entry: the key field is a
// password box, typing a key saves it to the server settings, and the sign-up link is there.
// usage: NODE_PATH=<folder with playwright-core> node comfyui_settings.cjs <comfyui url> <chrome> <profile dir> <screenshot>
const { chromium } = require('playwright-core');

const [base, chrome, profile, screenshot] = process.argv.slice(2);
const KEY = 'sk-typed-in-browser-0000';

(async () => {
	const context = await chromium.launchPersistentContext(profile, { executablePath: chrome, headless: true });
	const problems = [];
	try {
		const page = context.pages()[0] || (await context.newPage());
		await page.goto(base, { waitUntil: 'domcontentloaded' });
		await page.waitForFunction(() => window.app && window.app.extensionManager && window.app.extensionManager.command,
			null, { timeout: 90000 });
		await page.evaluate(() => window.app.extensionManager.command.execute('Comfy.ShowSettingsDialog'));
		await page.getByText('SteadyRouter', { exact: true }).first().click({ timeout: 30000 });
		const field = page.locator('input[type="password"]').first();
		await field.waitFor({ timeout: 30000 });
		if ((await field.getAttribute('autocomplete')) !== 'off') problems.push('key field: autocomplete is not off');
		await field.fill(KEY);
		await field.press('Tab');
		const link = page.locator('a[href*="sign-up"]').first();
		if (!(await link.count())) problems.push('no sign-up link in the SteadyRouter settings');
		else if ((await link.getAttribute('target')) !== '_blank') problems.push('sign-up link does not open a new tab');
		await page.waitForTimeout(1500);
		await page.screenshot({ path: screenshot });
		const saved = await page.evaluate(async () => (await fetch('/settings/SteadyRouter.ApiKey')).json());
		if (saved !== KEY) problems.push(`server settings hold ${JSON.stringify(saved)} instead of the typed key`);
	} catch (err) {
		problems.push(`browser step failed: ${err.message.split('\n')[0]}`);
	} finally {
		await context.close();
	}
	for (const p of problems) console.log('FAIL:', p);
	console.log('settings UI:', problems.length ? `${problems.length} problems` : 'ok');
	process.exit(problems.length ? 1 : 0);
})();
