package org.unauticna.myenginesmsgateway;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public final class SmsSentReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context,Intent intent) {
        String id=intent.getStringExtra("jobId");if(id==null||!id.matches("[a-f0-9]{32}"))return;
        boolean ok=getResultCode()==Activity.RESULT_OK;
        try {
            JobJournal.outcome(context,id,ok);
            GatewayService.report(context,ok?"SMS передана оператору. Ожидаю задания.":"Телефон не отправил SMS. Проверь SIM, связь и баланс.");
        } catch(Exception error){GatewayService.report(context,"Не удалось сохранить результат SMS. Повторной отправки не будет.");}
    }
}
