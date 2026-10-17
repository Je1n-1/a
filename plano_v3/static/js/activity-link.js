export function activityLink(row) {
  const params = row.project_id ? new URLSearchParams({project:row.project_id}) : new URLSearchParams({subject:row.subject_id||'free',title:row.title});
  if(row.project_id && row.step_id) params.set('step',row.step_id);
  if(!row.project_id && row.topic_id){params.set('topic',row.topic_id);params.set('kind',row.session_kind||'study');}
  return '/?'+params;
}
