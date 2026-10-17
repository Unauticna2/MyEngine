package org.unauticna.myenginesmsgateway;

import android.content.Context;
import java.net.URI;
import org.json.JSONObject;

final class GatewayConfig {
    final String origin,token,ownPhone;final int dailyLimit;
    GatewayConfig(String origin,String token,String ownPhone,int limit) throws Exception {
        URI uri=new URI(origin.trim());
        if(!"https".equals(uri.getScheme())||uri.getHost()==null||uri.getRawUserInfo()!=null||uri.getRawQuery()!=null||uri.getRawFragment()!=null||!(uri.getPath().isEmpty()||"/".equals(uri.getPath())))
            throw new Exception("Адрес сервера: https://имя.onrender.com без пути");
        if(!token.matches("[A-Za-z0-9_-]{32,128}"))throw new Exception("Нужен ключ из phone-token.txt");
        if(!ownPhone.matches("\\+[1-9][0-9]{7,14}"))throw new Exception("Номер SIM: +кодстраныномер, без пробелов");
        if(limit<1||limit>100)throw new Exception("Лимит: от 1 до 100 SMS в сутки");
        this.origin=origin.trim().replaceAll("/+$","");this.token=token;this.ownPhone=ownPhone;this.dailyLimit=limit;
    }
    void save(Context c) throws Exception {
        JSONObject data=new JSONObject();data.put("origin",origin);data.put("token",token);data.put("ownPhone",ownPhone);data.put("dailyLimit",dailyLimit);Vault.put(c,"config",data.toString());
    }
    static GatewayConfig load(Context c) throws Exception {
        JSONObject data=new JSONObject(Vault.get(c,"config","{}"));
        return new GatewayConfig(data.getString("origin"),data.getString("token"),data.getString("ownPhone"),data.getInt("dailyLimit"));
    }
}
