package org.unauticna.myenginesmsgateway;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.ArrayList;

public final class MainActivity extends Activity {
    private EditText origin,token,phone,limit;private TextView status;private LinearLayout form;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Runnable refresh=new Runnable(){public void run(){status.setText(Vault.preferences(MainActivity.this).getString("status","Шлюз остановлен"));handler.postDelayed(this,1000);}};
    private int dp(int x){return (int)(getResources().getDisplayMetrics().density*x);}
    private TextView label(String text,int size) {
        TextView view=new TextView(this);view.setText(text);view.setTextSize(size);view.setTextColor(Color.rgb(25,48,38));view.setPadding(0,dp(10),0,dp(6));form.addView(view);return view;
    }
    private EditText input(String name,int type) {
        label(name,14);EditText view=new EditText(this);view.setInputType(type);view.setSingleLine(true);form.addView(view,new LinearLayout.LayoutParams(-1,-2));return view;
    }
    private void button(String text,View.OnClickListener action){Button b=new Button(this);b.setText(text);b.setAllCaps(false);b.setOnClickListener(action);form.addView(b,new LinearLayout.LayoutParams(-1,dp(56)));}
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE,WindowManager.LayoutParams.FLAG_SECURE);
        ScrollView scroll=new ScrollView(this);form=new LinearLayout(this);form.setOrientation(LinearLayout.VERTICAL);form.setPadding(dp(24),dp(32),dp(24),dp(32));scroll.addView(form);setContentView(scroll);
        label("MYENGINE · R21",13);label("Твой телефон отправляет коды",28);
        label("Приложение для владельца сервера. Игрокам его устанавливать не нужно. SMS оплачиваются по тарифу SIM; сообщения самому себе не отправляются.",15);
        origin=input("HTTPS-адрес сервера Render",InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_URI);origin.setHint("https://имя.onrender.com");
        phone=input("Номер этой SIM с кодом страны",InputType.TYPE_CLASS_PHONE);phone.setHint("+кодстраныномер");
        token=input("Ключ телефона из phone-token.txt",InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        limit=input("Максимум SMS в сутки (UTC)",InputType.TYPE_CLASS_NUMBER);limit.setText("20");
        try{GatewayConfig c=GatewayConfig.load(this);origin.setText(c.origin);phone.setText(c.ownPhone);token.setText(c.token);limit.setText(String.valueOf(c.dailyLimit));}catch(Exception ignored){}
        status=label("",16);
        button("Сохранить настройки",v->save());button("Запустить отправку",v->startRequested());
        button("Остановить",v->stopService(new Intent(this,GatewayService.class)));
        button("Настройки SIM / связи",v->startActivity(new Intent(Settings.ACTION_WIRELESS_SETTINGS)));
        label("Для работы в фоне оставь уведомление включённым. Телефону нужны связь, интернет и питание. После перезагрузки открой приложение и снова нажми «Запустить». Пароль владельца вводится на сайте входа, а не здесь.",14);
    }
    private boolean save() {
        try {
            if(GatewayService.running)throw new Exception("Сначала останови шлюз, затем меняй настройки");
            new GatewayConfig(origin.getText().toString(),token.getText().toString().trim(),phone.getText().toString().trim(),Integer.parseInt(limit.getText().toString())).save(this);
            GatewayService.report(this,"Настройки сохранены. Можно запускать.");return true;
        } catch(Exception e){new AlertDialog.Builder(this).setMessage(e.getMessage()==null?"Проверь настройки":e.getMessage()).setPositiveButton("ОК",null).show();return false;}
    }
    private void startRequested() {
        if(GatewayService.running)return;if(!save())return;
        ArrayList<String> permissions=new ArrayList<>();
        if(checkSelfPermission(Manifest.permission.SEND_SMS)!=PackageManager.PERMISSION_GRANTED)permissions.add(Manifest.permission.SEND_SMS);
        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)permissions.add(Manifest.permission.POST_NOTIFICATIONS);
        if(!permissions.isEmpty()){requestPermissions(permissions.toArray(new String[0]),21);return;}
        confirmStart();
    }
    private void confirmStart() {
        new AlertDialog.Builder(this).setTitle("Включить отправку SMS?")
            .setMessage("Телефон начнёт автоматически отправлять коды зарегистрированным игрокам. SMS расходуются по тарифу выбранной SIM. Остановить можно здесь или через уведомление.")
            .setNegativeButton("Отмена",null).setPositiveButton("Запустить",(d,w)->{try{startForegroundService(new Intent(this,GatewayService.class));}catch(Exception e){GatewayService.report(this,"Android не разрешил запуск службы. Открой приложение и повтори.");}}).show();
    }
    @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] results) {
        super.onRequestPermissionsResult(code,permissions,results);
        if(code==21) {
            if(checkSelfPermission(Manifest.permission.SEND_SMS)==PackageManager.PERMISSION_GRANTED&&(Build.VERSION.SDK_INT<33||checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED))confirmStart();
            else GatewayService.report(this,"Для запуска нужны разрешения SMS и уведомления. Включи их в настройках приложения.");
        }
    }
    @Override protected void onResume(){super.onResume();handler.post(refresh);}
    @Override protected void onPause(){handler.removeCallbacks(refresh);super.onPause();}
}
