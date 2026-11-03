import {useEffect, useRef, useState} from 'react';
import {api} from '../api/client';

type CaptchaSettings={enabled:boolean;provider:'local'|'turnstile'|'recaptcha';site_key:string|null;ttl_seconds:number;captcha_id?:string;image?:string};
type Props={resetKey:number;onProof:(proof:{captcha_id?:string;captcha_answer?:string;captcha_token?:string},ready:boolean)=>void};

declare global {
 interface Window {
  turnstile?:{render:(element:HTMLElement,options:Record<string,unknown>)=>string;remove?:(id:string)=>void;reset?:(id?:string)=>void};
  grecaptcha?:{render:(element:HTMLElement,options:Record<string,unknown>)=>number;reset?:(id?:number)=>void};
 }
}

export default function CaptchaControl({resetKey,onProof}:Props){
 const [settings,setSettings]=useState<CaptchaSettings|null>(null);
 const [captchaId,setCaptchaId]=useState('');
 const [image,setImage]=useState('');
 const [error,setError]=useState('');
 const [localReload,setLocalReload]=useState(0);
 const widgetRef=useRef<HTMLDivElement>(null);
 const answerInputRef=useRef<HTMLInputElement>(null);
 const widgetId=useRef<string|number|null>(null);
 const proofCallback=useRef(onProof);
 proofCallback.current=onProof;
 const siteKey=import.meta.env.VITE_CAPTCHA_SITE_KEY as string|undefined;

 useEffect(()=>{let live=true;api.get('/auth/captcha').then(({data})=>{if(live){const next={...data,site_key:siteKey||data.site_key};setSettings(next);if(!next.enabled)proofCallback.current({},true)}}).catch(()=>{if(live)setError('Could not load CAPTCHA. Please refresh the page.')});return()=>{live=false}},[siteKey]);

 useEffect(()=>{
  if(!settings?.enabled)return;
  if(answerInputRef.current)answerInputRef.current.value='';setError('');proofCallback.current({},false);
  if(settings.provider==='local'){
   let live=true;let timer:number|undefined;
   const load=async()=>{setError('');try{const {data}=await api.get('/auth/captcha');if(!live)return;setCaptchaId(data.captcha_id||'');setImage(data.image||'');if(answerInputRef.current)answerInputRef.current.value='';setSettings(old=>old?{...old,ttl_seconds:data.ttl_seconds||old.ttl_seconds}:old);timer=window.setTimeout(()=>{if(!live)return;if(answerInputRef.current)answerInputRef.current.value='';proofCallback.current({},false);setError('CAPTCHA expired. A new image has been loaded.');void load()},(data.ttl_seconds||settings.ttl_seconds||180)*1000)}catch{if(live)setError('Could not load CAPTCHA. Please use Refresh.')}};
   void load();
   return()=>{live=false;if(timer)window.clearTimeout(timer)};
  }
 },[resetKey,localReload,settings?.enabled,settings?.provider]);

 useEffect(()=>{
  if(!settings?.enabled||settings.provider==='local'||!settings.site_key||!widgetRef.current)return;
  const provider=settings.provider;const globalReady=()=>{
   if(!widgetRef.current)return;
   const callback=(token:string)=>proofCallback.current({captcha_token:token},!!token);
   const expired=()=>proofCallback.current({},false);
   if(provider==='turnstile'&&window.turnstile){widgetId.current=window.turnstile.render(widgetRef.current,{sitekey:settings.site_key,callback,'expired-callback':expired,'error-callback':expired})}
   if(provider==='recaptcha'&&window.grecaptcha){widgetId.current=window.grecaptcha.render(widgetRef.current,{sitekey:settings.site_key,callback,'expired-callback':expired})}
  };
  const scriptId=`bidease-${settings.provider}-script`;
  let script=document.getElementById(scriptId) as HTMLScriptElement|null;
  if(!script){script=document.createElement('script');script.id=scriptId;script.async=true;script.defer=true;script.src=settings.provider==='turnstile'?'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit':'https://www.google.com/recaptcha/api.js?render=explicit';document.head.appendChild(script)}
  script.addEventListener('load',globalReady);if((settings.provider==='turnstile'&&window.turnstile)||(settings.provider==='recaptcha'&&window.grecaptcha))globalReady();
  return()=>{script?.removeEventListener('load',globalReady);if(typeof widgetId.current==='string')window.turnstile?.remove?.(widgetId.current);widgetId.current=null};
 },[resetKey,settings?.enabled,settings?.provider,settings?.site_key]);

 const refresh=()=>{if(answerInputRef.current)answerInputRef.current.value='';proofCallback.current({},false);setError('');if(settings?.provider==='local'){setCaptchaId('');setImage('');setLocalReload(value=>value+1)}else if(typeof widgetId.current==='string')window.turnstile?.reset?.(widgetId.current);else if(typeof widgetId.current==='number')window.grecaptcha?.reset?.(widgetId.current)};
 if(!settings)return <div className="text-xs text-slate-500" role="status">Loading CAPTCHA…</div>;
 if(!settings.enabled)return null;
 return <section className="mb-4" aria-label="CAPTCHA verification"><div className="flex items-center justify-between mb-2"><label htmlFor="captcha-answer" className="text-sm font-medium">CAPTCHA</label><button type="button" className="text-xs text-brand underline" onClick={refresh}>Refresh</button></div>{settings.provider==='local'?<><img className="h-16 w-[190px] rounded border bg-white object-contain" src={image?`data:image/png;base64,${image}`:undefined} alt="Captcha image, use Refresh if you cannot read it"/><input ref={answerInputRef} id="captcha-answer" className="mt-2 w-full" type="text" autoComplete="off" spellCheck={false} aria-label="Type the characters you see" placeholder="Type the characters you see" onChange={event=>proofCallback.current({captcha_id:captchaId},!!captchaId&&!!event.currentTarget.value.trim())}/ ></>:<div ref={widgetRef} aria-label="CAPTCHA verification widget"/>}{error&&<p className="text-xs text-red-600 mt-1" role="alert">{error}</p>}</section>;
}
