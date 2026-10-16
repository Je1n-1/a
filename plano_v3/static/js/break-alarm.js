import {api, send, validateTimer, esc} from './api.js';

const panel = document.createElement('section');
panel.className = 'break-countdown card';
panel.hidden = true;
panel.setAttribute('aria-label', 'Intervalo programado');
document.querySelector('.topbar').after(panel);
let state = null, received = 0, context = null, sounding = false;
let releaseLock = null, soundInterval = null, verified = '', checking = false;
let lastCheck = 0, revision = 0, serverError = '';
const key = value => value?.break_until ? `${value.id}:${value.break_until}` : '';
const active = value => value?.status === 'paused' && value.break_until;
const remaining = () => state ? Math.max(0, Math.ceil((Date.parse(state.break_until) - Date.parse(state.server_now) - (performance.now() - received))/1000)) : 0;
const clock = seconds => [Math.floor(seconds/3600),Math.floor(seconds%3600/60),seconds%60].map(n=>String(n).padStart(2,'0')).join(':');

function beep() {
  if (context?.state !== 'running') return;
  for (let i=0;i<3;i++) {
    const oscillator=context.createOscillator(), gain=context.createGain();
    const start=context.currentTime+i*0.25;
    oscillator.frequency.value=i===1?880:660;
    gain.gain.setValueAtTime(0,start);
    gain.gain.linearRampToValueAtTime(0.12,start+0.02);
    gain.gain.linearRampToValueAtTime(0,start+0.18);
    oscillator.connect(gain);gain.connect(context.destination);
    oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};
    oscillator.start(start);oscillator.stop(start+0.2);
  }
}

export async function enableBreakSound(test=false) {
  try {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return false;
    context ||= new Audio();
    await context.resume();
    try {sessionStorage.setItem('plano-break-sound','enabled');} catch {}
    if (test) beep();
    tick();
    return context.state === 'running';
  } catch { return false; }
}

function stopSound() {
  clearInterval(soundInterval);soundInterval=null;
  releaseLock?.();releaseLock=null;
}

function startSound() {
  if (sounding || context?.state !== 'running') return;
  sounding=true;
  const alarmKey=key(state);
  const play=async lock=>{
    if (!lock || !active(state) || key(state)!==alarmKey || remaining()>0) return;
    beep();soundInterval=setInterval(beep,2500);
    await new Promise(resolve=>{releaseLock=resolve;});
  };
  const task=navigator.locks ? navigator.locks.request('plano-break-sound',{ifAvailable:true},play) : play(true);
  task.catch(()=>{}).finally(()=>{sounding=false;});
}

export function updateBreakTimer(value) {
  const previousKey=key(state);
  state=active(value)?value:null;
  received=performance.now();++revision;
  if (!state || key(state)!==previousKey) {
    stopSound();verified='';serverError='';
  }
  panel.hidden=!state;
  if (!state) return;
  const deadline=new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',timeZone:'America/Sao_Paulo'}).format(new Date(state.break_until));
  panel.innerHTML=`<div><span class="eyebrow">INTERVALO DE ESTUDO</span><h2 data-break-title>Volta prevista às ${esc(deadline)}</h2><p>${esc(state.title)} · horário de São Paulo</p><p class="field-help">O intervalo continua até você retomar. As pausas curtas ficam paradas. Mantenha uma aba do site aberta para ouvir o alarme.</p><p data-break-error class="form-error" role="status"></p></div><strong class="break-digits" data-break-countdown></strong><div class="actions"><button class="button secondary" data-break-sound>Ativar / testar som</button><button class="button ghost" data-break-clear>Cancelar aviso</button><a class="button primary" href="/">Abrir relógio</a></div>`;
  panel.querySelector('[data-break-sound]').onclick=()=>enableBreakSound(true);
  panel.querySelector('[data-break-clear]').onclick=async e=>{
    const target=state;e.target.disabled=true;
    try {
      const result=validateTimer(await send(`/timer/${target.id}/break-clear`,{version:target.version}));
      updateBreakTimer(result);
      window.dispatchEvent(new CustomEvent('timer-state-changed',{detail:result}));
      window.dispatchEvent(new Event('session-refresh'));
      const channel=typeof BroadcastChannel==='function'?new BroadcastChannel('plano-session'):null;
      channel?.postMessage('changed');channel?.close();
    } catch(error) {
      panel.querySelector('[data-break-error]').textContent=error.message;
      e.target.disabled=false;
      await confirmState();
    }
  };
  try {if (!context && sessionStorage.getItem('plano-break-sound')==='enabled') enableBreakSound();} catch {}
  tick();
}

async function confirmState() {
  if (checking || !state) return;
  checking=true;lastCheck=performance.now();
  const requested=key(state), generation=revision;
  try {
    const value=validateTimer(await api('/timer'),true);
    if (revision!==generation) return;
    serverError='';
    if (key(value)===requested && active(value)) verified=requested;
    updateBreakTimer(value);
  } catch {
    serverError='Sem conexão para confirmar o intervalo. O alarme aguarda a reconexão.';
    stopSound();verified='';
    if (state) panel.querySelector('[data-break-error]').textContent=serverError;
  } finally {checking=false;}
}

function tick() {
  if (!state) return;
  const seconds=remaining(), expired=seconds===0;
  panel.querySelector('[data-break-countdown]').textContent=clock(seconds);
  panel.classList.toggle('break-expired',expired);
  panel.querySelector('[data-break-clear]').textContent=expired?'Silenciar aviso':'Cancelar aviso';
  panel.querySelector('[data-break-sound]').hidden=context?.state==='running';
  if (expired) {
    panel.querySelector('[data-break-title]').textContent='O horário de retorno chegou. Hora de voltar?';
    if (verified===key(state) && !serverError) startSound();
    else if (performance.now()-lastCheck>3000) confirmState();
  }
}
setInterval(tick,1000);
// Uma aba oculta também confere se o relógio foi retomado em outra aba.
setInterval(()=>{if(state)confirmState();},10000);
window.addEventListener('focus',()=>{if(state)confirmState();});
document.addEventListener('pointerdown',()=>{if(state && context?.state!=='running')enableBreakSound();});
