package org.unauticna.myenginesmsgateway;

import android.content.Context;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import org.json.JSONObject;

final class JobJournal {
    private static JSONObject read(Context c) throws Exception {return new JSONObject(Vault.get(c,"journal","{}"));}
    static synchronized int today(Context c) throws Exception {
        JSONObject j=read(c);long day=System.currentTimeMillis()/86400000L;
        return j.optLong("day",-1)==day?j.optInt("count",0):0;
    }
    static synchronized boolean beforeSend(Context c,JSONObject job,int limit) throws Exception {
        JSONObject j=read(c),jobs=j.optJSONObject("jobs");if(jobs==null)jobs=new JSONObject();
        String id=job.getString("id");if(jobs.has(id))return false;
        long now=System.currentTimeMillis()/1000,day=now/86400;int count=j.optLong("day",-1)==day?j.optInt("count",0):0;
        if(count>=limit)throw new Exception("Достигнут суточный лимит SMS");
        Iterator<String> it=jobs.keys();List<String> remove=new ArrayList<>();
        while(it.hasNext()){String key=it.next();if(jobs.getJSONObject(key).optLong("expiresAt")<now-172800)remove.add(key);}
        for(String key:remove)jobs.remove(key);
        JSONObject entry=new JSONObject();entry.put("id",id);entry.put("claimToken",job.getString("claimToken"));entry.put("status","unknown");
        entry.put("expiresAt",job.getLong("expiresAt"));entry.put("attemptAt",now);
        jobs.put(id,entry);j.put("jobs",jobs);j.put("day",day);j.put("count",count+1);
        // Commit BEFORE SmsManager: uncertain/crashed sends are never submitted again.
        Vault.put(c,"journal",j.toString());return true;
    }
    static synchronized void outcome(Context c,String id,boolean success) throws Exception {
        JSONObject j=read(c),jobs=j.optJSONObject("jobs");if(jobs==null||!jobs.has(id))return;
        JSONObject entry=jobs.getJSONObject(id);entry.put("status",success?"sent":"failed");Vault.put(c,"journal",j.toString());
    }
    static synchronized List<JSONObject> receipts(Context c) throws Exception {
        JSONObject jobs=read(c).optJSONObject("jobs");List<JSONObject> out=new ArrayList<>();if(jobs==null)return out;
        long now=System.currentTimeMillis()/1000;Iterator<String> keys=jobs.keys();
        while(keys.hasNext()&&out.size()<3) {
            JSONObject e=jobs.getJSONObject(keys.next());
            if(!e.optBoolean("acked")&&e.getLong("expiresAt")+600>now&&(!"unknown".equals(e.getString("status"))||e.getLong("attemptAt")+60<now))
                out.add(new JSONObject(e.toString()));
        }
        return out;
    }
    static synchronized void acknowledged(Context c,String id,String status) throws Exception {
        JSONObject j=read(c),jobs=j.optJSONObject("jobs");if(jobs==null||!jobs.has(id))return;
        JSONObject e=jobs.getJSONObject(id);
        // A later modem result can supersede an earlier unknown acknowledgement.
        if(status.equals(e.getString("status"))&&!"unknown".equals(status))e.put("acked",true);
        Vault.put(c,"journal",j.toString());
    }
}
