import { expect, test } from "@playwright/test";

test("submits an analysis and follows it to the published result", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("What event or claim should Benmo investigate?").fill(
    "Oil prices rose sharply. Which airline margins could be affected?",
  );
  await page.getByRole("button", { name: "Map the causal chain" }).click();
  await expect(page).toHaveURL(/\/analysis\/11111111-1111-4111-8111-111111111111\/progress/);
  await expect(page.getByRole("heading", { name: /Building the causal record/ })).toBeVisible();
  await expect(page).toHaveURL(/\/analysis\/ana_mock_public/);
  await expect(page.getByRole("heading", { name: "Oil prices increased materially." })).toBeVisible();
  await expect(page.getByText("The argument, edge by edge")).toBeVisible();
  const socialCard = await page.request.get("/analysis/ana_mock_public/og");
  expect(socialCard.ok()).toBeTruthy();
  expect(socialCard.headers()["content-type"]).toContain("image/png");
});

test("renders the research archive and methodology", async ({ page }) => {
  await page.goto("/explore");
  await expect(page.getByRole("heading", { name: "Published causal analyses" })).toBeVisible();
  await page.getByRole("link", { name: "Methodology" }).first().click();
  await expect(page.getByRole("heading", { name: "A claim should show how it could be wrong." })).toBeVisible();
});
