import {useRef} from 'react';
import type {UseFormReturn} from 'react-hook-form';

type Props={form:UseFormReturn<Record<string,any>>;showErrors:boolean;readOnly:boolean};

export default function MailTrackingCard({form,showErrors,readOnly}:Props){
 const sent=form.watch('mail_sent')??'No';
 const received=form.watch('mail_received')??'No';
 const sentInput=useRef<HTMLInputElement|null>(null);
 const receivedInput=useRef<HTMLInputElement|null>(null);
 const sentToField=form.register('mail_sent_to');
 const receivedFromField=form.register('mail_received_from');
 const setChoice=(key:string,value:'Yes'|'No',nameKey:string,dateKey:string)=>{
  form.setValue(key,value,{shouldDirty:true,shouldValidate:showErrors});
  if(value==='No')form.setValue(nameKey,null,{shouldDirty:true,shouldValidate:showErrors});
  if(value==='Yes'&&!form.getValues(dateKey)){
   const now=new Date();
   const today=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
   form.setValue(dateKey,today,{shouldDirty:true,shouldValidate:showErrors});
  }
 };
 const sentError=form.formState.errors.mail_sent_to?.message;
 const receivedError=form.formState.errors.mail_received_from?.message;
 return <section className="card p-5">
  <h2 className="font-bold mb-4">Mail tracking</h2>
  <div className="grid gap-4 md:grid-cols-2">
   <div className="field">
    <label htmlFor="mail_sent">Request initiated (mail sent)</label>
    <select id="mail_sent" value={sent} disabled={readOnly} onChange={event=>{const next=event.target.value as 'Yes'|'No';setChoice('mail_sent',next,'mail_sent_to','mail_sent_on');if(next==='Yes')sentInput.current?.focus()}}>
     <option value="No">No</option><option value="Yes">Yes</option>
    </select>
    <div className="mt-3">
     <label htmlFor="mail_sent_to">Sent to</label>
     <input id="mail_sent_to" maxLength={80} placeholder={sent==='Yes'?'Enter name':'Select Yes to enter'} readOnly={readOnly||sent!=='Yes'} aria-readonly={readOnly||sent!=='Yes'} tabIndex={readOnly||sent!=='Yes'?-1:0} className={readOnly||sent!=='Yes'?'bg-slate-100 text-slate-500 cursor-not-allowed':''} {...sentToField} ref={element=>{sentToField.ref(element);sentInput.current=element}} onBlur={event=>{sentToField.onBlur(event);const value=event.target.value.trim();form.setValue('mail_sent_to',value||null,{shouldDirty:true,shouldValidate:showErrors})}}/>
     {showErrors&&sentError&&<span className="err">{String(sentError)}</span>}
    </div>
   </div>
   <div className="field">
    <label htmlFor="mail_received">Final document received</label>
    <select id="mail_received" value={received} disabled={readOnly} onChange={event=>{const next=event.target.value as 'Yes'|'No';setChoice('mail_received',next,'mail_received_from','mail_received_on');if(next==='Yes')receivedInput.current?.focus()}}>
     <option value="No">No</option><option value="Yes">Yes</option>
    </select>
    <div className="mt-3">
     <label htmlFor="mail_received_from">Received from</label>
     <input id="mail_received_from" maxLength={80} placeholder={received==='Yes'?'Enter name':'Select Yes to enter'} readOnly={readOnly||received!=='Yes'} aria-readonly={readOnly||received!=='Yes'} tabIndex={readOnly||received!=='Yes'?-1:0} className={readOnly||received!=='Yes'?'bg-slate-100 text-slate-500 cursor-not-allowed':''} {...receivedFromField} ref={element=>{receivedFromField.ref(element);receivedInput.current=element}} onBlur={event=>{receivedFromField.onBlur(event);const value=event.target.value.trim();form.setValue('mail_received_from',value||null,{shouldDirty:true,shouldValidate:showErrors})}}/>
     {showErrors&&receivedError&&<span className="err">{String(receivedError)}</span>}
    </div>
   </div>
  </div>
 </section>;
}
