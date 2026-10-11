import {
  $,
  api,
  dialog,
  esc,
  toast
} from './api.js';
import {
  timestamp,
  clock
} from './study-format.js';

export async function openStorage() {
  const el = dialog('Armazenamento e backup', '<p>Conferindo o banco…</p>');
  try {
    const d = await api('/diagnostics');
    if (!el.open) return;
    $('.dialog-content', el).innerHTML = `<p>Seus registros são salvos neste computador.</p><dl class="diagnostic"><dt>Banco ativo</dt><dd>${esc(d.path)}</dd><dt>Versão do esquema</dt><dd>${esc(d.schema.join(', '))}</dd><dt>Integridade</dt><dd>${esc(d.integrity)} · ${d.foreign_key_violations} relações inválidas</dd><dt>Último backup</dt><dd>${d.last_backup?esc(timestamp(d.last_backup.created_at))+'<br>'+esc(d.last_backup.path)+(d.last_backup.available?'':'<br>Cópia local não encontrada; confira o arquivo baixado.'):'Ainda não registrado'}</dd></dl><div class="storage-actions"><button type="button" class="button primary" id="create-backup">Criar backup</button><button type="button" class="button secondary" id="recover-backup">Recuperar uma cópia</button></div><p class="field-help">Guarde também o arquivo baixado em outro dispositivo. A recuperação valida o backup e cria um arquivo separado para conferência.</p>`;
    $('#create-backup', el).onclick = backup;
    $('#recover-backup', el).onclick = recover;
  } catch (error) {
    if (el.open) $('.dialog-content', el).textContent = error.message;
  }
}

function backup() {
  dialog('Criar backup?', '<p>Uma cópia consistente será guardada na pasta local de backups e baixada pelo navegador. Você pode continuar estudando durante a cópia.</p>', async () => {
    const response = await fetch('/api/backups', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        confirmed: true
      })
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Não foi possível criar o backup.');
    }
    const url = URL.createObjectURL(await response.blob()),
      link = document.createElement('a');
    link.href = url;
    link.download = response.headers.get('Content-Disposition')?.match(/filename="?([^";]+)"?/)?.[1] || 'plano-backup.db';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast('Backup validado e salvo. Confira também o download.');
  }, 'Criar e baixar');
}

function recover() {
  const el = dialog('Recuperar em arquivo separado', `<p>Selecione um backup gerado pelo Plano V3 (até 64 MB). A cópia será validada antes de recuperar.</p><label>Arquivo de backup<input type="file" name="file" accept=".db,.sqlite,.sqlite3" required></label><label class="storage-confirm"><input type="checkbox" name="confirmed" required>Confirmo a criação de uma cópia separada. O banco ativo continuará em uso.</label>`, async () => {
    const body = new FormData();
    body.append('file', $('[name=file]', el).files[0]);
    body.append('confirmed', 'true');
    const result = await api('/backups/recover', {
      method: 'POST',
      body
    });
    setTimeout(() => dialog('Cópia recuperada', `<p>Integridade e relações verificadas. Seu banco ativo continua o mesmo.</p><dl class="diagnostic"><dt>Arquivo recuperado</dt><dd>${esc(result.path)}</dd><dt>Conteúdo</dt><dd>${result.courses} curso(s), ${result.subjects} disciplina(s), ${result.sessions} sessão(ões)</dd><dt>Estudo concluído</dt><dd>${clock(result.effective_seconds)} líquidos · ${clock(result.break_seconds)} de pausa</dd></dl><p>Para conferir a cópia, abra-a em uma instância separada conforme o guia de recuperação do README. A troca do banco de uso diário é uma etapa manual.</p>`, null), 0);
  }, 'Validar e recuperar');
}
