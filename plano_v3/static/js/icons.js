const names=new Set(['home','book','target','layers','chart','sun','moon','database','clock','calendar','play','plus','check','arrow','download','chip','code']);
export const icon=name=>`<svg class="ui-icon" aria-hidden="true"><use href="/static/icons.svg#${names.has(name)?name:'layers'}"></use></svg>`;
