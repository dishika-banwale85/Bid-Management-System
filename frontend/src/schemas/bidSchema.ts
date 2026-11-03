import {z} from 'zod';

const dateValue=z.string().trim().min(1,'This date is required').refine(value=>{
  if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;
  const [year,month,day]=value.split('-').map(Number);
  const parsed=new Date(Date.UTC(year,month-1,day));
  return parsed.getUTCFullYear()===year&&parsed.getUTCMonth()===month-1&&parsed.getUTCDate()===day;
},'Enter a valid date');

const optionalDate=z.union([dateValue,z.literal(''),z.null(),z.undefined()]).transform(value=>value||'');

export const bidCreateSchema=z.object({
  bid_status:z.enum(['SUBMITTED','NOT_SUBMITTED','WIN','WITHDRAW','LOSE']).default('NOT_SUBMITTED'),
  client_name:z.string().trim().min(1,'Client name is required').max(200,'Maximum 200 characters'),
  department:z.string().trim().optional().default(''),
  client_address:z.string().trim().min(1,'Client address is required').max(500,'Maximum 500 characters'),
  rfp_number:z.string().trim().min(1,'RFP number is required').max(120,'Maximum 120 characters'),
  project_title:z.string().trim().min(1,'Project title is required').max(250,'Maximum 250 characters'),
  rfp_published_date:dateValue,
  prebid_query_deadline:optionalDate,
  prebid_query_na:z.boolean().default(false),
  prebid_meeting_date:optionalDate,
  prebid_meeting_na:z.boolean().default(false),
  submission_deadline:dateValue,
  tender_opening_date:dateValue,
}).superRefine((value,context)=>{
  const today=new Date();today.setHours(0,0,0,0);
  const todayString=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  if(value.submission_deadline<todayString)context.addIssue({code:z.ZodIssueCode.custom,path:['submission_deadline'],message:'Bid submission date cannot be before today'});
  if(value.tender_opening_date<todayString)context.addIssue({code:z.ZodIssueCode.custom,path:['tender_opening_date'],message:'Bid opening date cannot be before today'});
  if(value.rfp_published_date>value.submission_deadline)context.addIssue({code:z.ZodIssueCode.custom,path:['rfp_published_date'],message:'RFP published date must be on or before bid submission date'});
  if(value.submission_deadline>value.tender_opening_date)context.addIssue({code:z.ZodIssueCode.custom,path:['tender_opening_date'],message:'Bid opening date must be on or after bid submission date'});
  for(const [field,na,date] of [
    ['prebid_query_deadline',value.prebid_query_na,value.prebid_query_deadline],
    ['prebid_meeting_date',value.prebid_meeting_na,value.prebid_meeting_date],
  ] as const){
    if(!na&&!date)context.addIssue({code:z.ZodIssueCode.custom,path:[field],message:'Enter a date or select Not applicable'});
    if(date&&(date<value.rfp_published_date||date>value.submission_deadline))context.addIssue({code:z.ZodIssueCode.custom,path:[field],message:'Date must be between RFP published date and bid submission date'});
  }
}).transform(value=>({
  ...value,
  prebid_query_deadline:value.prebid_query_na?null:(value.prebid_query_deadline||null),
  prebid_meeting_date:value.prebid_meeting_na?null:(value.prebid_meeting_date||null),
}));

export type BidCreateForm=z.input<typeof bidCreateSchema>;
export type BidCreateValues=z.output<typeof bidCreateSchema>;
