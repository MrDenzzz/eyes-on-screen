const russian = new Intl.PluralRules("ru");

/** The Russian word form for `count`: forms are for 1, 2-4 and 5+ ("кадр", "кадра", "кадров"). */
export function ruPlural(count: number, forms: readonly [string, string, string]): string {
  const rule = russian.select(count);
  return rule === "one" ? forms[0] : rule === "few" ? forms[1] : forms[2];
}

/** A decimal with a comma, as Russian writes it: 1,5. */
export function ruDecimal(value: number, digits: number): string {
  return value.toFixed(digits).replace(".", ",");
}
