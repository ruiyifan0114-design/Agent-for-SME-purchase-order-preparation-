import { test, expect, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

const header = { 'X-API-Key': 'local-service-change-me' }
async function start(page: Page, scenario = '03') {
  await page.goto('/#data')
  await expect(page.getByRole('heading', { name: 'Data intake', exact: true })).toBeVisible()
  await page.getByRole('button', { name: new RegExp(`SCENARIO ${scenario}`) }).click()
  const modal = page.getByRole('dialog', { name: 'Run daily procurement check' })
  await expect(modal).toBeVisible()
  await modal.getByRole('button', { name: 'Start check', exact: true }).click()
  await expect(modal).toBeHidden()
  await expect(
    page.locator('.stat-card').filter({ hasText: 'SKUs in this review' }).locator('strong'),
  ).toHaveText('10')
  return await page.getByLabel('Current procurement run').inputValue()
}
async function nav(page: Page, name: string) {
  await page.locator('.sidebar nav').getByRole('button', { name, exact: true }).click()
}
async function approve(page: Page, supplier: string) {
  const card = page
    .locator('.draft-card')
    .filter({ has: page.getByRole('heading', { name: supplier, exact: true }) })
  await card.getByRole('button', { name: 'Review & approve' }).click()
  const modal = page.getByRole('dialog', { name: 'Approve this purchase order?' })
  await expect(modal.getByRole('button', { name: 'Confirm approval' })).toBeDisabled()
  await modal
    .getByLabel('Review comment')
    .fill('Synthetic browser test: reviewed source, quantities and dates.')
  await modal.getByRole('checkbox').check()
  await modal.getByRole('button', { name: 'Confirm approval' }).click()
  await expect(modal).toBeHidden()
  await expect(card.locator('.badge')).toHaveText('Approved')
  return card
}

test('normal review, explicit approval, export, critical edit and rejection', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  const runId = await start(page, '01')
  await expect(
    page.locator('.stat-card').filter({ hasText: 'Blocked SKUs' }).locator('strong'),
  ).toHaveText('00')
  await expect(page.locator('.progress-pair')).toContainText('100%')
  await nav(page, 'SKU check')
  await expect(page.locator('.sku-table tbody tr')).toHaveCount(10)
  await page.getByRole('button', { name: 'View evidence for SKU-001' }).click()
  await expect(page.getByRole('dialog')).toContainText('Raw requirement')
  await page.getByRole('button', { name: 'Close dialog' }).click()
  await nav(page, 'PO drafts 3')
  await expect(page.locator('.draft-card')).toHaveCount(3)
  const supplier = await approve(page, 'Synthetic Supplier A')
  const downloadPromise = page.waitForEvent('download')
  await supplier.getByRole('button', { name: 'Export approved PO' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/^PO-.*\.csv$/)
  expect(await readFile((await download.path())!, 'utf8')).toContain('PRE_TAX')
  await supplier.getByRole('button', { name: 'Edit SKU-001 line' }).click()
  const edit = page.getByRole('dialog', { name: 'Edit purchase order line' })
  await edit.getByLabel('Order quantity').fill('100')
  await edit
    .getByLabel('Reason for edit')
    .fill('Synthetic reviewer increases quantity to a valid pack multiple')
  await edit.getByRole('button', { name: 'Save & require review' }).click()
  await expect(edit).toBeHidden()
  await expect(supplier.locator('.badge')).toHaveText('Needs review')
  await expect(supplier.getByRole('button', { name: 'Export approved PO' })).toHaveCount(0)
  await approve(page, 'Synthetic Supplier A')
  await supplier.getByRole('button', { name: 'Approval history' }).click()
  await expect(page.getByRole('dialog')).toContainText('INVALIDATED')
  await expect(page.getByRole('dialog')).toContainText('Demo Human Reviewer')
  await page.getByRole('button', { name: 'Close dialog' }).click()
  const supplierB = page.locator('.draft-card').filter({ hasText: 'Synthetic Supplier B' })
  await supplierB.getByRole('button', { name: 'Reject', exact: true }).click()
  const reject = page.getByRole('dialog', { name: 'Reject this purchase order?' })
  await reject
    .getByLabel('Review comment')
    .fill('Synthetic review: hold pending delivery discussion')
  await reject.getByRole('checkbox').check()
  await reject.getByRole('button', { name: 'Confirm rejection' }).click()
  await expect(reject).toBeHidden()
  await expect(supplierB.locator('.badge')).toHaveText('Rejected')
  await page.reload()
  await expect(page.getByLabel('Current procurement run')).toHaveValue(runId)
  await expect(page.locator('.draft-card')).toHaveCount(3)
  await page.getByRole('button', { name: 'Sync drafts' }).click()
  await expect(
    page.getByText('Drafts synchronized with the current SKU decisions.', { exact: true }),
  ).toBeVisible()
  await expect(page.locator('.draft-card')).toHaveCount(3)
  expect(errors).toEqual([])
})

test('timely incoming prevents purchase; late incoming preserves timing gap', async ({ page }) => {
  await start(page, '02')
  await nav(page, 'SKU check')
  const timely = page.locator('tbody tr').filter({ hasText: 'SKU-001' })
  const late = page.locator('tbody tr').filter({ hasText: 'SKU-002' })
  await expect(timely).toContainText('No reorder')
  await expect(late).toContainText('Reorder')
  await page.getByRole('button', { name: 'View evidence for SKU-002' }).click()
  await expect(page.getByRole('dialog')).toContainText('SYNTHETIC-LATE')
  await expect(page.getByRole('dialog')).toContainText('80')
  await page.getByRole('button', { name: 'Close dialog' }).click()
  await nav(page, 'Exceptions')
  await expect(page.getByRole('heading', { name: 'late open po' })).toBeVisible()
})

test('all three blockers corrected through forms and persisted in supplier drafts', async ({
  page,
}) => {
  const runId = await start(page, '03')
  await expect(page.locator('.progress-pair')).toContainText('70%')
  await expect(page.locator('.progress-pair')).toContainText('100%')
  await page.screenshot({ path: 'test-results/dashboard-desktop.png', fullPage: true })
  await nav(page, 'Exceptions 3')
  await page
    .locator('.exception-card')
    .filter({ has: page.getByRole('heading', { name: 'missing price', exact: true }) })
    .getByRole('button', { name: 'Resolve issue' })
    .click()
  let modal = page.getByRole('dialog', { name: 'Resolve exception' })
  await modal.getByLabel('Unit price', { exact: true }).fill('4.50')
  await modal.getByLabel('Reason for correction').fill('Confirmed synthetic test price')
  await modal.getByRole('button', { name: 'Save & recheck SKU' }).click()
  await expect(modal).toBeHidden()
  await expect(page.getByRole('heading', { name: 'missing price', exact: true })).toHaveCount(0)
  await expect(page.locator('.sidebar nav')).toContainText('Exceptions2')
  const run = (await (await page.request.get(`/api/v1/runs/${runId}`, { headers: header })).json())
    .data
  await page
    .locator('.exception-card')
    .filter({ has: page.getByRole('heading', { name: 'missing inventory', exact: true }) })
    .getByRole('button', { name: 'Resolve issue' })
    .click()
  modal = page.getByRole('dialog', { name: 'Resolve exception' })
  await modal.getByRole('button', { name: 'Add inventory snapshots record' }).click()
  await modal.getByLabel('On hand', { exact: true }).fill('10')
  await modal.getByLabel('Snapshot date').fill(run.as_of)
  await modal.getByLabel('Reason for correction').fill('Confirmed synthetic physical stock count')
  await modal.getByRole('button', { name: 'Save & recheck SKU' }).click()
  await expect(modal).toBeHidden()
  await expect(page.getByRole('heading', { name: 'missing inventory', exact: true })).toHaveCount(0)
  await page
    .locator('.exception-card')
    .filter({ has: page.getByRole('heading', { name: 'supplier not approved', exact: true }) })
    .getByRole('button', { name: 'Resolve issue' })
    .click()
  modal = page.getByRole('dialog', { name: 'Resolve exception' })
  await modal.getByLabel('Approved for SKU').selectOption('true')
  await modal
    .getByLabel('Reason for correction')
    .fill('Human confirms this synthetic supplier relationship')
  await modal.getByRole('button', { name: 'Save & recheck SKU' }).click()
  await expect(modal).toBeHidden()
  await expect(
    page.getByRole('heading', { name: 'supplier not approved', exact: true }),
  ).toHaveCount(0)
  await nav(page, 'SKU check')
  await expect(page.locator('.sku-table tbody tr')).toHaveCount(10)
  await page.getByRole('button', { name: 'Blocked 0', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'No matching SKU results' })).toBeVisible()
  await nav(page, 'PO drafts 3')
  const row = page.locator('.draft-card tbody tr').filter({ hasText: 'SKU-004' })
  await expect(row).toContainText('4.5000')
  await expect(page.locator('.draft-card tbody tr')).toHaveCount(9)
})

test('agent explains stored state and opens a price correction without silently saving', async ({
  page,
}) => {
  const id = await start(page, '03')
  await page.getByRole('button', { name: 'Ask agent', exact: true }).click()
  await page.getByLabel('Message the procurement agent').fill('Why is SKU-004 blocked?')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByRole('dialog', { name: 'SKU decision evidence' })).toBeVisible()
  await page.getByRole('button', { name: 'Close dialog' }).click()
  await page.getByLabel('Message the procurement agent').fill('Its unit price is 4.50.')
  await page.getByRole('button', { name: 'Send message' }).click()
  const dialog = page.getByRole('dialog', { name: 'Resolve exception' })
  await expect(dialog.getByLabel('Unit price', { exact: true })).toHaveValue('4.50')
  const result = (
    await (await page.request.get(`/api/v1/runs/${id}/skus/SKU-004`, { headers: header })).json()
  ).data
  expect(result.status).toBe('BLOCKED')
  expect(result.context.commercial[0].unit_price).toBeNull()
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
})

test('a failed approval remains an error, with no approved export', async ({ page }) => {
  await start(page, '01')
  await nav(page, 'PO drafts 3')
  const supplier = page.locator('.draft-card').filter({ hasText: 'Synthetic Supplier A' })
  await page.route('**/api/v1/drafts/*/approve', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'TEST_OUTAGE', message: 'Injected approval outage. No approval saved.' },
      }),
    }),
  )
  await supplier.getByRole('button', { name: 'Review & approve' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Review comment').fill('Testing failure reporting only')
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: 'Confirm approval' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Injected approval outage')
  await expect(supplier.getByRole('button', { name: 'Export approved PO' })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Keep as is' }).click()
})

test('CSV upload validates records and keeps validation findings visible', async ({ page }) => {
  await page.goto('/#data')
  const tables = [
    'sku_master',
    'supplier_master',
    'supplier_sku',
    'inventory_snapshot',
    'demand',
    'open_po',
  ]
  await page
    .getByLabel('Upload source files')
    .setInputFiles(tables.map((t) => path.resolve(`../demo/${t}.csv`)))
  await page.getByRole('button', { name: 'Upload & validate' }).click()
  const modal = page.getByRole('dialog', { name: 'Run daily procurement check' })
  await expect(modal).toBeVisible()
  await modal.getByLabel('Warehouse', { exact: true }).fill('SYNTHETIC-WH-1')
  await modal.getByRole('button', { name: 'Start check', exact: true }).click()
  await expect(modal).toBeHidden()
  await expect(
    page.locator('.stat-card').filter({ hasText: 'Blocked SKUs' }).locator('strong'),
  ).toHaveText('03')
  await nav(page, 'Data intake')
  const batch = page.locator('.batch').first()
  await batch.locator('summary').click()
  await expect(batch).toContainText('TEAM TO DEFINE')
})

test('responsive layout and keyboard dialog close on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'A clear view. A better order.' })).toBeVisible()
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy()
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true })
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await page.locator('.sidebar').getByRole('button', { name: 'Data intake', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Data intake', exact: true })).toBeVisible()
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy()
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await page.getByRole('button', { name: 'Quick guide' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeHidden()
})

test('an interrupted scan resumes the same run and keeps all expected SKUs visible', async ({
  page,
}) => {
  const demo = (await (await page.request.get('/api/v1/demo/normal', { headers: header })).json())
    .data
  const batch = (
    await (
      await page.request.post('/api/v1/imports?filename=resume-case.json', {
        headers: header,
        data: demo.dataset,
      })
    ).json()
  ).data
  const created = (
    await (
      await page.request.post('/api/v1/runs', {
        headers: header,
        data: { ...demo.policy, batch_id: batch.id },
      })
    ).json()
  ).data
  await page.goto('/')
  await expect(page.getByLabel('Current procurement run')).toHaveValue(created.id)
  await expect(page.getByRole('button', { name: 'Resume current check' })).toBeVisible()
  await nav(page, 'SKU check')
  await expect(page.locator('.sku-table tbody tr')).toHaveCount(10)
  await expect(page.locator('.sku-table .badge')).toHaveText(Array(10).fill('Not checked'))
  await nav(page, 'Overview')
  await page.getByRole('button', { name: 'Resume current check' }).click()
  await expect(
    page.locator('.stat-card').filter({ hasText: 'Ready to reorder' }).locator('strong'),
  ).toHaveText('09')
  await expect(page.getByLabel('Current procurement run')).toHaveValue(created.id)
  await nav(page, 'Audit trail')
  await expect(page.locator('.detail-list')).toContainText('resume-case.json')
  await expect(page.locator('.audit-event').first()).toBeVisible()
  await page.locator('.audit-event').first().getByRole('button').click()
  await expect(page.getByText('Recorded input', { exact: true })).toBeVisible()
})

test('JSON filename survives intake and rejected datasets stay visible', async ({ page }) => {
  await page.goto('/#data')
  const demo = (await (await page.request.get('/api/v1/demo/normal', { headers: header })).json())
    .data
  demo.dataset.sku_master.push(demo.dataset.sku_master[0])
  await page
    .getByLabel('Upload source files')
    .setInputFiles({
      name: 'invalid-duplicate-master.json',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify(demo.dataset)),
    })
  await page.getByRole('button', { name: 'Upload & validate' }).click()
  await expect(page.getByRole('alert')).toContainText('Import rejected')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const batch = page.locator('.batch').filter({ hasText: 'invalid-duplicate-master.json' }).first()
  await expect(batch.locator('.badge')).toHaveText('Rejected')
  await batch.locator('summary').click()
  await expect(batch).toContainText('unique')
  await expect(batch.getByRole('button', { name: 'Run check with this batch' })).toHaveCount(0)
})
