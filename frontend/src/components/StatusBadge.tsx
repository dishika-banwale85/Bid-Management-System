export default function StatusBadge({value}:{value:string}){
  const color=value==='COMPLETED'?'bg-emerald-100 text-emerald-800':value==='REJECTED'?'bg-red-100 text-red-700':value==='IN_APPROVAL'?'bg-blue-100 text-blue-800':value==='DRAFT'?'bg-slate-100 text-slate-600':'bg-amber-100 text-amber-800';
  return <span className={`badge ${color}`}>{value.replaceAll('_',' ')}</span>;
}
