package org.unauticna.myenginesmsgateway;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.net.Uri;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.telephony.SmsManager;
import android.telephony.SubscriptionManager;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

public final class GatewayService extends Service {
    static volatile boolean running=false;
    static final String CHANNEL="myengine_sms_gateway",STOP="org.unauticna.myenginesmsgateway.STOP";
    private ScheduledExecutorService worker;private PowerManager.WakeLock wakeLock;
    private GatewayConfig config;private GatewayApi api;
    private volatile boolean active=false;
    @Override public IBinder onBind(Intent i){return null;}
    private Notification notification(String text) {
        PendingIntent open=PendingIntent.getActivity(this,1,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stop=PendingIntent.getService(this,2,new Intent(this,GatewayService.class).setAction(STOP),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this,CHANNEL).setSmallIcon(R.drawable.ic_gateway).setContentTitle("MyEngine · SMS-шлюз включён")
            .setContentText(text).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true).addAction(new Notification.Action.Builder(null,"Остановить",stop).build()).build();
    }
    static void report(Context c,String message) {
        Vault.preferences(c).edit().putString("status",message).apply();
        if(c instanceof GatewayService&&running)((GatewayService)c).getSystemService(NotificationManager.class).notify(21,((GatewayService)c).notification(message));
    }
    @Override public int onStartCommand(Intent intent,int flags,int id) {
        if(intent!=null&&STOP.equals(intent.getAction())){stopSelf();return START_NOT_STICKY;}
        if(running)return START_NOT_STICKY;
        getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel(CHANNEL,"Отправка SMS",NotificationManager.IMPORTANCE_LOW));
        if(Build.VERSION.SDK_INT>=34)startForeground(21,notification("Подключение…"),ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(21,notification("Подключение…"));
        try {
            config=GatewayConfig.load(this);api=new GatewayApi(config);running=true;active=true;
            wakeLock=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"MyEngine:SmsGateway");wakeLock.setReferenceCounted(false);
            worker=Executors.newSingleThreadScheduledExecutor();worker.scheduleWithFixedDelay(this::tick,0,5,TimeUnit.SECONDS);
        }catch(Exception e){report(this,"Проверь настройки приложения");stopSelf();}
        return START_NOT_STICKY;
    }
    private void tick() {
        if(!active)return;
        try {
            synchronized(this){if(!active)return;wakeLock.acquire(120000L);}
            if(checkSelfPermission(Manifest.permission.SEND_SMS)!=PackageManager.PERMISSION_GRANTED)throw new Exception("Разреши отправку SMS в настройках приложения");
            int subscription=SubscriptionManager.getDefaultSmsSubscriptionId();
            if(!SubscriptionManager.isValidSubscriptionId(subscription))throw new Exception("Выбери SIM по умолчанию для SMS в настройках Android");
            for(JSONObject receipt:JobJournal.receipts(this)) {
                api.post("/api/gateway/jobs/"+receipt.getString("id")+"/result",new JSONObject().put("claimToken",receipt.getString("claimToken")).put("status",receipt.getString("status")));
                JobJournal.acknowledged(this,receipt.getString("id"),receipt.getString("status"));
            }
            if(JobJournal.today(this)>=config.dailyLimit)throw new Exception("Достигнут суточный лимит. Сегодня новых SMS не будет.");
            JSONObject response=api.post("/api/gateway/claim",new JSONObject());
            if(!active)return;
            JSONObject job=response.optJSONObject("job");
            if(job==null){report(this,"Подключён. Ожидаю задания. Сегодня: "+JobJournal.today(this)+" / "+config.dailyLimit);return;}
            String id=job.getString("id"),phone=job.getString("phone"),code=job.getString("code"),claim=job.getString("claimToken");
            if(!id.matches("[a-f0-9]{32}")||!phone.matches("\\+[1-9][0-9]{7,14}")||!code.matches("[0-9]{6}")||!claim.matches("[A-Za-z0-9_-]{32,128}"))throw new Exception("Сервер вернул некорректное задание");
            if(!JobJournal.beforeSend(this,job,config.dailyLimit))return;
            if(job.getLong("expiresAt")*1000L<=System.currentTimeMillis()||phone.equals(config.ownPhone)) {
                JobJournal.outcome(this,id,false);report(this,phone.equals(config.ownPhone)?"SMS себе отменена. Для владельца используй пароль.":"Срок задания истёк. Проверь время на телефоне.");return;
            }
            synchronized(this) {
                if(!active){JobJournal.outcome(this,id,false);return;}
                Intent sent=new Intent(this,SmsSentReceiver.class).setData(Uri.parse("myengine-sms:"+id)).putExtra("jobId",id);
                PendingIntent callback=PendingIntent.getBroadcast(this,0,sent,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
                try {
                    SmsManager.getSmsManagerForSubscriptionId(subscription).sendTextMessage(phone,null,"MyEngine login code: "+code+". Valid for 5 minutes.",callback,null);
                    report(this,"SMS передана Android. Ожидаю результат оператора.");
                }catch(Exception e){JobJournal.outcome(this,id,false);throw e;}
            }
        } catch(Exception error) {
            if(active)report(this,error instanceof java.io.IOException?"Нет связи с сервером. Проверю снова автоматически.":(error.getMessage()==null?"Не удалось выполнить задание":error.getMessage()));
        }
    }
    @Override public synchronized void onDestroy() {
        active=false;running=false;if(worker!=null)worker.shutdownNow();
        if(wakeLock!=null&&wakeLock.isHeld())wakeLock.release();
        report(this,"Шлюз остановлен. Новые SMS не отправляются.");stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy();
    }
}
