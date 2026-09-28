import { test, expect } from '@playwright/test'

test('manually entered goods run through agent, purchasing and finance approval, export and versioned editing', async ({
  page,
}) => {
  await page.goto('/#data')
  await page.getByRole('button', { name: 'Build dataset manually' }).click()
  const editor = page.getByRole('dialog', { name: 'Build procurement dataset' })
  await editor.getByLabel('Dataset name', { exact: true }).fill('competition-manual.json')
  await editor.getByRole('button', { name: 'Add record', exact: true }).click()
  const fill = async (table: string, label: string, value: string) =>
    editor.getByLabel(`${table} row 1 ${label}`, { exact: true }).fill(value)
  const select = async (table: string, label: string, value: string) =>
    editor.getByLabel(`${table} row 1 ${label}`, { exact: true }).selectOption(value)
  const tab = async (name: string) => {
    await editor.getByRole('tab', { name: new RegExp(`^${name}`) }).click()
    await editor.getByRole('button', { name: 'Add record', exact: true }).click()
  }
  const today = new Date().toLocaleDateString('en-CA')
  await fill('Goods / SKUs', 'SKU ID', 'COMP-001')
  await fill('Goods / SKUs', 'Description', 'Competition goods')
  await fill('Goods / SKUs', 'Unit', 'pcs')
  await fill('Goods / SKUs', 'Safety stock', '20')
  await fill('Goods / SKUs', 'Target stock', '100')
  await tab('Suppliers')
  await fill('Suppliers', 'Supplier ID', 'COMP-SUP')
  await fill('Suppliers', 'Supplier name', 'Competition supplier')
  await select('Suppliers', 'Approved', 'true')
  await fill('Suppliers', 'Currency', 'SGD')
  await tab('Supplier terms')
  await fill('Supplier terms', 'SKU ID', 'COMP-001')
  await fill('Supplier terms', 'Supplier ID', 'COMP-SUP')
  await select('Supplier terms', 'Approved for SKU', 'true')
  await fill('Supplier terms', 'Unit price', '50.0000')
  await fill('Supplier terms', 'Currency', 'SGD')
  await fill('Supplier terms', 'MOQ', '1')
  await fill('Supplier terms', 'Pack multiple', '1')
  await fill('Supplier terms', 'Lead time (days)', '0')
  await fill('Supplier terms', 'Updated date', today)
  await tab('Inventory')
  await fill('Inventory', 'SKU ID', 'COMP-001')
  await fill('Inventory', 'On hand', '0')
  await fill('Inventory', 'Snapshot date', today)
  await editor.getByRole('button', { name: 'Validate & create batch' }).click()
  await expect(editor).toBeHidden()
  const runForm = page.getByRole('dialog', { name: 'Run daily procurement check' })
  await runForm.getByLabel('Warehouse', { exact: true }).fill('COMP-WH')
  await runForm.getByRole('button', { name: 'Start check', exact: true }).click()
  await expect(runForm).toBeHidden()
  await expect(page.getByLabel('Current procurement run')).not.toHaveValue('')
  const originalRun = await page.getByLabel('Current procurement run').inputValue()
  await page
    .locator('.sidebar nav')
    .getByRole('button', { name: 'PO drafts 1', exact: true })
    .click()
  const draft = page.locator('.draft-card')
  await expect(draft).toContainText('5,000.00')
  await draft.getByRole('button', { name: 'Review & approve', exact: true }).click()
  let approval = page.getByRole('dialog', { name: 'Purchasing Manager approval' })
  await approval.getByLabel('Review comment').fill('Purchasing reviewed competition evidence')
  await approval.getByRole('checkbox').check()
  await approval.getByRole('button', { name: 'Confirm approval' }).click()
  await expect(draft.locator('.badge')).toHaveText('Finance review')
  await expect(draft.getByRole('button', { name: 'Export approved PO' })).toHaveCount(0)
  await draft.getByRole('button', { name: 'Finance review & approve' }).click()
  approval = page.getByRole('dialog', { name: 'Finance Manager review' })
  await approval.getByLabel('Review comment').fill('Finance reviewed competition spend')
  await approval.getByRole('checkbox').check()
  await approval.getByRole('button', { name: 'Confirm approval' }).click()
  await expect(draft.locator('.badge')).toHaveText('Approved')
  const download = page.waitForEvent('download')
  await draft.getByRole('button', { name: 'Export approved PO' }).click()
  expect((await download).suggestedFilename()).toMatch(/^PO-/)

  await page
    .locator('.sidebar nav')
    .getByRole('button', { name: 'Data intake', exact: true })
    .click()
  const batch = page.locator('.batch').filter({ hasText: 'competition-manual.json' }).first()
  await batch.locator('summary').click()
  await batch.getByRole('button', { name: 'Edit as new batch' }).click()
  await fill('Goods / SKUs', 'Description', 'Updated competition goods')
  await editor.getByRole('button', { name: 'Duplicate Goods / SKUs row 1' }).click()
  await expect(editor.getByLabel('Goods / SKUs row 2 SKU ID', { exact: true })).toHaveValue(
    'COMP-001',
  )
  await editor.getByRole('button', { name: 'Delete Goods / SKUs row 2' }).click()
  await editor.getByRole('button', { name: 'Validate & create batch' }).click()
  await expect(runForm).toBeVisible()
  const headers = { 'X-API-Key': 'local-service-change-me' }
  const original = await page.request.get(`/api/v1/runs/${originalRun}/skus/COMP-001`, { headers })
  expect(original.ok()).toBeTruthy()
  expect((await original.json()).data.context.sku.description).toBe('Competition goods')
})

test('free chat sends conversation history, renders evidence and navigates to requested page', async ({
  page,
}) => {
  await page.goto('/#dashboard')
  let calls = 0
  await page.route('**/api/v1/agent/message', async (route) => {
    const body = route.request().postDataJSON()
    if (calls++)
      expect(
        body.history.some((m: { content: string }) => m.content.includes('supplier spend')),
      ).toBeTruthy()
    await route.fulfill({
      json: {
        data: {
          message: '**Supplier spend** comes from the selected review.',
          action: calls === 2 ? 'NAVIGATE' : 'NONE',
          page: 'data',
          provider: 'DeepSeek ReAct',
          tools_used: ['get_decision_cockpit'],
        },
      },
    })
  })
  await page.getByRole('button', { name: 'Ask agent', exact: true }).click()
  await page.getByLabel('Message the procurement agent').fill('Analyze supplier spend')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.locator('.chat-message-body strong').last()).toHaveText('Supplier spend')
  await page.getByLabel('Message the procurement agent').fill('Open the data page')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByRole('heading', { name: 'Data intake', exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
