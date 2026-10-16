export const textKey=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim();
export function moduleGroups(rows) {
  const groups=new Map();
  for (const row of rows) {
    const name=String(row.period||'').trim()||'Sem módulo informado';
    const key=textKey(name);
    if (!groups.has(key)) groups.set(key,{name,rows:[]});
    groups.get(key).rows.push(row);
  }
  return [...groups.values()];
}
