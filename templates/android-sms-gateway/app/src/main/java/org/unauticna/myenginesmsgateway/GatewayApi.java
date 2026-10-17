package org.unauticna.myenginesmsgateway;

import javax.net.ssl.HttpsURLConnection;
import java.net.URL;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

final class GatewayApi {
    private final GatewayConfig config;
    GatewayApi(GatewayConfig config){this.config=config;}
    JSONObject post(String path,JSONObject data) throws Exception {
        HttpsURLConnection connection=(HttpsURLConnection)new URL(config.origin+path).openConnection();
        connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(15000);connection.setReadTimeout(20000);
        connection.setRequestMethod("POST");connection.setDoOutput(true);connection.setRequestProperty("Authorization","Bearer "+config.token);
        connection.setRequestProperty("Content-Type","application/json");connection.setRequestProperty("Accept","application/json");
        byte[] payload=data.toString().getBytes(StandardCharsets.UTF_8);connection.setFixedLengthStreamingMode(payload.length);
        try {
            try(OutputStream stream=connection.getOutputStream()){stream.write(payload);}
            int status=connection.getResponseCode();
            if(status==401||status==403)throw new Exception("Сервер отклонил ключ телефона");
            if(status==503)throw new Exception("SMS-шлюз на сервере выключен или недоступен");
            if(status!=200)throw new Exception("Ошибка сервера: "+status);
            try(InputStream stream=connection.getInputStream();ByteArrayOutputStream bytes=new ByteArrayOutputStream()) {
                byte[] part=new byte[1024];int count;
                while((count=stream.read(part))!=-1){if(bytes.size()+count>16384)throw new Exception("Слишком большой ответ сервера");bytes.write(part,0,count);}
                return new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));
            }
        } finally {connection.disconnect();}
    }
}
