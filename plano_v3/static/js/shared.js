import {
  $,
  toast
} from './api.js';
$('#date-label').textContent = new Intl.DateTimeFormat('pt-BR', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  timeZone: 'America/Sao_Paulo'
}).format(new Date());
document.querySelectorAll('#diagnostics,[data-storage]').forEach(button => {
  button.onclick = async () => {
    try {
      await (await import('./storage.js')).openStorage();
    } catch (error) {
      toast(error.message);
    }
  };
});
