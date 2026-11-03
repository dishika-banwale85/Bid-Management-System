import {useMemo,useState} from 'react';
import type {ReactNode} from 'react';
import {useNavigate} from 'react-router-dom';
import {useQueryClient} from '@tanstack/react-query';
import {useForm} from 'react-hook-form';
import type {Resolver} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {Building2,CalendarDays,Check,FileText,LoaderCircle,AlertCircle,Upload,X} from 'lucide-react';
import {checkRfpNumber,createBid,type User,type BidStatus} from '../api/client';
import {bidCreateSchema,type BidCreateForm,type BidCreateValues} from '../schemas/bidSchema';

const today=()=>{const now=new Date();return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`};
const labelDate=(value:string)=>new Date(`${value}T00:00:00`).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'});
const daysBetween=(left:string,right:string)=>Math.round((Date.parse(`${right}T00:00:00Z`)-Date.parse(`${left}T00:00:00Z`))/86400000);

function FieldError({message}:{message?:string}){return message?<p className="mt-1 text-xs text-red-700" role="alert">{message}</p>:null}
function SectionHeading({icon,title}:{icon:ReactNode;title:string}){return <div className="mb-5 flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-brand">{icon}</span><h2 className="text-base font-bold text-ink">{title}</h2></div>}

const bidStatusLabels:Record<BidStatus,string>={SUBMITTED:'Submitted',NOT_SUBMITTED:'Not submitted',WIN:'Win',WITHDRAW:'Withdraw',LOSE:'Lose'};
export default function CreateBidPage({user}:{user?:User|null}){
 const navigate=useNavigate();const queryClient=useQueryClient();const [duplicate,setDuplicate]=useState(false);const [duplicateLoading,setDuplicateLoading]=useState(false);const [submitError,setSubmitError]=useState('');
 const [rfpFile,setRfpFile]=useState<File|null>(null),[rfpFileError,setRfpFileError]=useState('');const canManage=user?.role==='BID_TEAM';
 const form=useForm<BidCreateForm,unknown,BidCreateValues>({resolver:zodResolver(bidCreateSchema) as Resolver<BidCreateForm,unknown,BidCreateValues>,mode:'onBlur',defaultValues:{client_name:'',department:'',client_address:'',rfp_number:'',project_title:'',rfp_published_date:'',prebid_query_deadline:'',prebid_query_na:false,prebid_meeting_date:'',prebid_meeting_na:false,submission_deadline:'',tender_opening_date:'',bid_status:'NOT_SUBMITTED'}});
 const values=form.watch();const errors=form.formState.errors;
 const timeline=useMemo(()=>[
  {label:'Published',date:values.rfp_published_date},
  {label:'Query deadline',date:values.prebid_query_na?'':values.prebid_query_deadline},
  {label:'Pre-bid meeting',date:values.prebid_meeting_na?'':values.prebid_meeting_date},
  {label:'Submission',date:values.submission_deadline},
  {label:'Opening',date:values.tender_opening_date},
 ].filter((item):item is {label:string;date:string}=>typeof item.date==='string'&&item.date.length>0).sort((a,b)=>a.date.localeCompare(b.date)),[values]);
 const onSubmit=form.handleSubmit(async(data)=>{
  setSubmitError('');
  if(rfpFileError){setSubmitError(rfpFileError);return}
  try{
   const duplicateCheck=await checkRfpNumber(data.rfp_number);
   setDuplicate(duplicateCheck.exists);
   if(duplicateCheck.exists&&!window.confirm('A bid with this RFP number already exists. Create this bid anyway?'))return;
   const result=await createBid(data,canManage?rfpFile:undefined);
   await queryClient.invalidateQueries({queryKey:['bids']});
   navigate(`/bids/${result.id}`,{state:{toast:'Bid created successfully'}});
  }catch(error){setSubmitError(error instanceof Error?error.message:'Could not create the bid. Please try again.')}
 });
 const onRfpBlur=async()=>{
  const rfp=form.getValues('rfp_number').trim();
  setDuplicate(false);
  if(!rfp)return;
  setDuplicateLoading(true);
  try{const result=await checkRfpNumber(rfp);setDuplicate(result.exists)}
  catch(error){setSubmitError(error instanceof Error?error.message:'Could not check this RFP number.')}
  finally{setDuplicateLoading(false)}
 };
 const register=form.register;
 return <div className="-mx-2 -my-2 px-2 py-2 pb-24 sm:-mx-3 sm:px-3">
  <button type="button" className="mb-4 inline-flex items-center text-sm font-medium text-slate-500 hover:text-brand" onClick={()=>navigate('/bids')}>← Back to bids</button>
  <header className="mb-6"><h1 className="text-2xl font-bold text-ink">Create a new bid</h1><p className="mt-1 text-sm text-slate-500">Enter the key details from the RFP. You can add compliance requests next.</p></header>
  <form onSubmit={onSubmit} noValidate className="space-y-5">
   <section className="card p-5"><SectionHeading icon={<Building2 size={18}/>} title="Client"/><div className="grid gap-4 md:grid-cols-2">
    <div className="field"><label htmlFor="client_name">Client name <span className="text-red-700">*</span></label><input id="client_name" autoComplete="organization" maxLength={200} {...register('client_name')}/><FieldError message={errors.client_name?.message}/></div>
    <div className="field"><label htmlFor="department">Department</label><input id="department" maxLength={160} {...register('department')}/><FieldError message={errors.department?.message}/></div>
    <div className="field md:col-span-2"><label htmlFor="client_address">Client address <span className="text-red-700">*</span></label><textarea id="client_address" rows={3} maxLength={500} className="resize-y rounded-lg border border-slate-300 bg-white p-3 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-blue-600/10" {...register('client_address')}/><div className="flex justify-between"><FieldError message={errors.client_address?.message}/><span className="text-xs text-slate-500">{values.client_address?.length||0}/500</span></div></div>
   </div></section>

   <section className="card p-5"><SectionHeading icon={<FileText size={18}/>} title="RFP details"/><div className="grid gap-4 md:grid-cols-2">
    <div className="field"><label htmlFor="rfp_number">RFP number <span className="text-red-700">*</span></label><div className="relative"><input id="rfp_number" maxLength={120} aria-describedby="rfp-warning" {...register('rfp_number',{onBlur:onRfpBlur})}/>{duplicateLoading&&<LoaderCircle className="absolute right-3 top-3 animate-spin text-slate-400" size={16}/>}</div>{duplicate&&<p id="rfp-warning" className="mt-1 text-xs font-medium text-amber-800" role="status">A bid with this RFP number already exists. You can still create the bid after confirming.</p>}<FieldError message={errors.rfp_number?.message}/></div>
    <div className="field"><label htmlFor="project_title">Project title <span className="text-red-700">*</span></label><input id="project_title" maxLength={250} {...register('project_title')}/><FieldError message={errors.project_title?.message}/></div>
    <div className="field"><label htmlFor="rfp_published_date">RFP published date <span className="text-red-700">*</span></label><input id="rfp_published_date" type="date" max={values.submission_deadline||undefined} {...register('rfp_published_date')}/><FieldError message={errors.rfp_published_date?.message}/></div>
    <div className="field"><label htmlFor="bid_status">Status of bid</label>{canManage?<select id="bid_status" {...register('bid_status')}>{Object.entries(bidStatusLabels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select>:<span className="inline-flex rounded-full bg-slate-100 px-3 py-2 text-sm text-slate-600">Not submitted</span>}</div>
    <div className="field"><span className="block text-sm font-medium text-ink">RFP (PDF or Word)</span>{canManage?<label className="mt-1 flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-slate-300 p-3 text-sm hover:border-brand"><Upload size={16} className="text-brand"/><span className="min-w-0 flex-1 truncate">{rfpFile?.name||'Choose PDF, DOC or DOCX · up to 10 MB'}</span><input type="file" accept=".pdf,.doc,.docx" className="sr-only" onChange={event=>{const file=event.target.files?.[0]||null;setRfpFileError('');if(file&&(!['.pdf','.doc','.docx'].includes(file.name.toLowerCase().slice(file.name.lastIndexOf('.')))||file.size>10*1024*1024)){setRfpFileError('Only PDF or Word files up to 10 MB');setRfpFile(null)}else setRfpFile(file);event.currentTarget.value=''}}/></label>:<p className="mt-1 text-sm text-slate-500">Optional RFP attachment</p>}{rfpFile&&<button type="button" className="mt-1 inline-flex items-center gap-1 text-xs text-slate-500 underline" onClick={()=>setRfpFile(null)}><X size={13}/>Remove selected file</button>}{rfpFileError&&<FieldError message={rfpFileError}/>}</div>
   </div></section>

   <section className="card p-5"><SectionHeading icon={<CalendarDays size={18}/>} title="Key dates"/><div className="grid gap-4 md:grid-cols-2">
    <div className="field"><label htmlFor="prebid_query_deadline">Pre-bid query submission date {!values.prebid_query_na&&<span className="text-red-700">*</span>}</label>{!values.prebid_query_na&&<><input id="prebid_query_deadline" type="date" min={values.rfp_published_date||undefined} max={values.submission_deadline||undefined} {...register('prebid_query_deadline')}/><FieldError message={errors.prebid_query_deadline?.message}/></>}<label className="mt-1 inline-flex items-center gap-2 text-sm font-normal text-slate-600"><input type="checkbox" className="!h-4 !w-4 accent-blue-600" {...register('prebid_query_na')}/>Not applicable</label></div>
    <div className="field"><label htmlFor="prebid_meeting_date">Pre-bid meeting date {!values.prebid_meeting_na&&<span className="text-red-700">*</span>}</label>{!values.prebid_meeting_na&&<><input id="prebid_meeting_date" type="date" min={values.rfp_published_date||undefined} max={values.submission_deadline||undefined} {...register('prebid_meeting_date')}/><FieldError message={errors.prebid_meeting_date?.message}/></>}<label className="mt-1 inline-flex items-center gap-2 text-sm font-normal text-slate-600"><input type="checkbox" className="!h-4 !w-4 accent-blue-600" {...register('prebid_meeting_na')}/>Not applicable</label></div>
    <div className="field"><label htmlFor="submission_deadline">Bid submission date <span className="text-red-700">*</span></label><input id="submission_deadline" type="date" min={today()} max={values.tender_opening_date||undefined} {...register('submission_deadline')}/><FieldError message={errors.submission_deadline?.message}/></div>
    <div className="field"><label htmlFor="tender_opening_date">Bid opening date <span className="text-red-700">*</span></label><input id="tender_opening_date" type="date" min={values.submission_deadline>today()?values.submission_deadline:today()} {...register('tender_opening_date')}/><FieldError message={errors.tender_opening_date?.message}/></div>
   </div>
   <div className="mt-6 rounded-xl border border-slate-200 bg-wash p-4"><h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink"><CalendarDays size={16} className="text-brand"/>Date timeline</h3>{timeline.length?<div className="flex items-center gap-3 overflow-x-auto pb-2">{timeline.map((item,index)=><div className="flex shrink-0 items-center gap-3" key={item.label}><div className="rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{item.label}</div><div className="mt-1 text-sm font-semibold text-ink">{labelDate(item.date)}</div></div>{index<timeline.length-1&&<span className="whitespace-nowrap text-xs text-slate-500">{daysBetween(item.date,timeline[index+1]?.date||item.date)} days →</span>}</div>)}</div>:<p className="text-sm text-slate-500">Dates will appear here as you fill in the form.</p>}</div>
   </section>
   {(submitError||rfpFileError)&&<div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert"><AlertCircle size={17} className="mt-0.5 shrink-0"/>{rfpFileError||submitError}</div>}
   <footer className="sticky bottom-0 z-10 -mx-2 flex items-center justify-end gap-3 border-t border-slate-200 bg-white/95 px-2 py-3 backdrop-blur sm:-mx-3 sm:px-3"><button type="button" className="btn secondary" onClick={()=>navigate('/bids')}>Cancel</button><button type="submit" disabled={form.formState.isSubmitting||duplicateLoading} className="btn">{form.formState.isSubmitting?<><LoaderCircle size={16} className="animate-spin"/>Creating…</>:<><Check size={16}/>Create bid</>}</button></footer>
  </form>
 </div>;
}
