import {useState} from 'react';
import type {User} from '../api/client';
export function useStoredSession(){
  const [user,setUser]=useState<User|null>(()=>{if(!localStorage.getItem('bidease-token')){localStorage.removeItem('bidease-user');return null}try{const stored=JSON.parse(localStorage.getItem('bidease-user')||'null') as User|null;const enteredName=localStorage.getItem('bidease-entered-name');return stored?{...stored,name:enteredName||stored.name,role:stored.role==='ADMIN'?'ADMIN':'BID_TEAM'}:null}catch{return null}});
  return {user,setUser};
}
