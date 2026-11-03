import {useState} from 'react';
import type {User} from '../api/client';
export function useStoredSession(){
  const [user,setUser]=useState<User|null>(()=>{if(!localStorage.getItem('bidease-token')){localStorage.removeItem('bidease-user');return null}try{return JSON.parse(localStorage.getItem('bidease-user')||'null') as User|null}catch{return null}});
  return {user,setUser};
}
