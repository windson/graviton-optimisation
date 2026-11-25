const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const day = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeZone: 'UTC' });

export const money = (value) => currency.format(Number(value));
export const date = (value) => day.format(new Date(value));
