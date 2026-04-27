import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/calendar' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

describe('RecurrencePicker', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders a select with preset options', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: null, startTime: '2024-06-10T09:00:00Z' },
    })
    const select = wrapper.find('select')
    expect(select.exists()).toBe(true)
    const options = select.findAll('option')
    const values = options.map(o => o.element.value)
    expect(values).toContain('none')
    expect(values).toContain('daily')
    expect(values).toContain('weekly')
    expect(values).toContain('weekdays')
    expect(values).toContain('monthly')
    expect(values).toContain('custom')
  })

  it('emits null when "Does not repeat" selected', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: 'FREQ=DAILY', startTime: '2024-06-10T09:00:00Z' },
    })
    const select = wrapper.find('select')
    await select.setValue('none')
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toBeNull()
  })

  it('emits FREQ=DAILY for daily preset', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: null, startTime: '2024-06-10T09:00:00Z' },
    })
    await wrapper.find('select').setValue('daily')
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted![0][0]).toBe('FREQ=DAILY')
  })

  it('emits FREQ=WEEKLY;BYDAY=MO for a Monday start_time', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    // 2024-06-10 is a Monday
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: null, startTime: '2024-06-10T09:00:00Z' },
    })
    await wrapper.find('select').setValue('weekly')
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted![0][0]).toBe('FREQ=WEEKLY;BYDAY=MO')
  })

  it('emits FREQ=WEEKLY;BYDAY=TU for a Tuesday start_time', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    // 2024-06-11 is a Tuesday
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: null, startTime: '2024-06-11T09:00:00Z' },
    })
    await wrapper.find('select').setValue('weekly')
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted![0][0]).toBe('FREQ=WEEKLY;BYDAY=TU')
  })

  it('emits FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR for weekdays preset', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: null, startTime: '2024-06-10T09:00:00Z' },
    })
    await wrapper.find('select').setValue('weekdays')
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted![0][0]).toBe('FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR')
  })

  it('emits FREQ=MONTHLY for monthly preset', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: null, startTime: '2024-06-10T09:00:00Z' },
    })
    await wrapper.find('select').setValue('monthly')
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted![0][0]).toBe('FREQ=MONTHLY')
  })

  it('shows custom text input when custom is selected', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: null, startTime: '2024-06-10T09:00:00Z' },
    })
    await wrapper.find('select').setValue('custom')
    expect(wrapper.find('[data-testid="rrule-custom-input"]').exists()).toBe(true)
  })

  it('emits raw rrule string from custom text input', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: null, startTime: '2024-06-10T09:00:00Z' },
    })
    await wrapper.find('select').setValue('custom')
    const input = wrapper.find('[data-testid="rrule-custom-input"]')
    await input.setValue('FREQ=YEARLY;BYMONTH=6;BYMONTHDAY=10')
    await input.trigger('change')
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    const lastEmit = emitted![emitted!.length - 1][0]
    expect(lastEmit).toBe('FREQ=YEARLY;BYMONTH=6;BYMONTHDAY=10')
  })

  it('selects "none" when modelValue is null', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: null, startTime: '2024-06-10T09:00:00Z' },
    })
    const select = wrapper.find('select')
    expect((select.element as HTMLSelectElement).value).toBe('none')
  })

  it('selects "daily" when modelValue is FREQ=DAILY', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: 'FREQ=DAILY', startTime: '2024-06-10T09:00:00Z' },
    })
    const select = wrapper.find('select')
    expect((select.element as HTMLSelectElement).value).toBe('daily')
  })

  it('selects "custom" when modelValue is an unrecognized rrule', async () => {
    const { default: RecurrencePicker } = await import('../RecurrencePicker.vue')
    const wrapper = mount(RecurrencePicker, {
      props: { modelValue: 'FREQ=YEARLY', startTime: '2024-06-10T09:00:00Z' },
    })
    const select = wrapper.find('select')
    expect((select.element as HTMLSelectElement).value).toBe('custom')
  })
})
