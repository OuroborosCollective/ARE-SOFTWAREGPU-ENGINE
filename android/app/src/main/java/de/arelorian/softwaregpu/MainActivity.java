package de.arelorian.softwaregpu;

import android.app.Activity;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.view.Gravity;
import android.view.View;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceError;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private WebView browser;
    private TextView status;
    private LinearLayout welcome;
    private String permittedHost = "";
    private static final String PREFS = "are_gradio_endpoint";
    private static final int BG = Color.rgb(12, 19, 33);
    private static final int PANEL = Color.rgb(25, 37, 55);
    private static final int FG = Color.rgb(242, 248, 255);
    private static final int MUTED = Color.rgb(190, 207, 222);
    private static final int CYAN = Color.rgb(51, 210, 217);

    static boolean validEndpoint(String value) {
        if (value == null) return false;
        Uri uri = Uri.parse(value.trim());
        return "https".equalsIgnoreCase(uri.getScheme()) && uri.getHost() != null
            && !uri.getHost().isEmpty() && uri.getEncodedAuthority() != null
            && !uri.getEncodedAuthority().contains("@")
            && uri.getPort() <= 65535 && uri.getPort() >= -1
            && uri.getFragment() == null;
    }

    private int dp(int n) { return (int)(n * getResources().getDisplayMetrics().density + .5f); }

    private TextView text(String value, int size, int color, boolean bold) {
        TextView v = new TextView(this);
        v.setText(value);
        v.setTextSize(size);
        v.setTextColor(color);
        if (bold) v.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        v.setPadding(0, dp(4), 0, dp(10));
        return v;
    }

    private GradientDrawable surface(int color, int radius) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(radius));
        return d;
    }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.setPadding(dp(16), dp(12), dp(16), dp(8));

        LinearLayout top = new LinearLayout(this);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.setOrientation(LinearLayout.HORIZONTAL);
        TextView brand = text("ARE  /  CPU-TESTLABOR", 17, CYAN, true);
        top.addView(brand, new LinearLayout.LayoutParams(0, -2, 1));
        Button settings = new Button(this);
        settings.setText("Verbindung");
        settings.setContentDescription("Verbindungseinstellungen öffnen");
        top.addView(settings);
        root.addView(top);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        welcome = new LinearLayout(this);
        welcome.setOrientation(LinearLayout.VERTICAL);
        welcome.setPadding(dp(16), dp(20), dp(16), dp(20));
        welcome.setBackground(surface(PANEL, 18));
        welcome.addView(text("Dein erster Grafiktest", 26, FG, true));
        welcome.addView(text("Du brauchst keine Gradio-Kenntnisse. Ein CPU-Rechner führt den Test aus; diese App zeigt Bedienung, Bild und Prüfergebnis.", 16, MUTED, false));
        welcome.addView(text("1  Sicheren Testserver verbinden", 17, FG, true));
        welcome.addView(text("Trage die HTTPS-Adresse des von dir bereitgestellten ARE-Testservers ein. Ohne Server kann die APK nicht selbst rendern.", 14, MUTED, false));
        EditText endpoint = new EditText(this);
        endpoint.setSingleLine(true);
        endpoint.setTextColor(FG);
        endpoint.setHintTextColor(MUTED);
        endpoint.setTextSize(16);
        endpoint.setHint("https://dein-testserver.example");
        endpoint.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        endpoint.setContentDescription("HTTPS-Adresse des ARE-Testservers");
        endpoint.setPadding(dp(12), dp(14), dp(12), dp(14));
        endpoint.setBackground(surface(BG, 10));
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        endpoint.setText(prefs.getString("endpoint", ""));
        welcome.addView(endpoint, new LinearLayout.LayoutParams(-1, dp(55)));
        welcome.addView(text("2  Vorlage auswählen · 3  Test starten", 17, FG, true));
        welcome.addView(text("Auf dem nächsten Bildschirm findest du Schnelltest, Standard, Detailtest und Referenzvergleich. Einstellungen werden automatisch ausgefüllt.", 14, MUTED, false));
        Button connect = new Button(this);
        connect.setText("Testlabor öffnen");
        connect.setTextColor(BG);
        connect.setTextSize(16);
        connect.setAllCaps(false);
        connect.setBackgroundTintList(android.content.res.ColorStateList.valueOf(CYAN));
        welcome.addView(connect, new LinearLayout.LayoutParams(-1, dp(56)));
        status = text("Noch nicht verbunden. Dein Test beginnt nach dem Verbinden.", 14, MUTED, false);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        welcome.addView(status);
        scroll.addView(welcome);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1f));

        browser = new WebView(this);
        browser.setVisibility(View.GONE);
        browser.getSettings().setJavaScriptEnabled(true);
        browser.getSettings().setDomStorageEnabled(true);
        browser.getSettings().setAllowFileAccess(false);
        browser.getSettings().setAllowContentAccess(false);
        browser.getSettings().setJavaScriptCanOpenWindowsAutomatically(false);
        browser.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri target = request.getUrl();
                return !("https".equalsIgnoreCase(target.getScheme())
                    && permittedHost.equalsIgnoreCase(target.getHost()));
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (url != null && "https".equalsIgnoreCase(Uri.parse(url).getScheme())) {
                    status.setText("Testlabor geladen. Wähle eine Vorlage und tippe auf Test starten.");
                }
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) {
                    browser.setVisibility(View.GONE);
                    scroll.setVisibility(View.VISIBLE);
                    status.setText("Verbindung fehlgeschlagen. Prüfe HTTPS-Adresse, Netzwerk und Serveranmeldung.");
                }
            }
        });
        root.addView(browser, new LinearLayout.LayoutParams(-1, 0, 1f));
        connect.setOnClickListener(v -> {
            String url = endpoint.getText().toString().trim();
            if (!validEndpoint(url)) {
                status.setText("Bitte eine gültige HTTPS-Adresse ohne Benutzerinfo eingeben.");
                return;
            }
            prefs.edit().putString("endpoint", url).apply();
            permittedHost = Uri.parse(url).getHost();
            status.setText("Verbinde mit " + permittedHost + " …");
            scroll.setVisibility(View.GONE);
            browser.setVisibility(View.VISIBLE);
            browser.loadUrl(url);
        });
        settings.setOnClickListener(v -> {
            browser.setVisibility(View.GONE);
            scroll.setVisibility(View.VISIBLE);
        });
        setContentView(root);
    }

    @Override public void onBackPressed() {
        if (browser.getVisibility() == View.VISIBLE && browser.canGoBack()) browser.goBack();
        else if (browser.getVisibility() == View.VISIBLE) {
            browser.setVisibility(View.GONE);
            welcome.getParent().requestLayout();
            ((View) welcome.getParent().getParent()).setVisibility(View.VISIBLE);
        } else super.onBackPressed();
    }
    @Override protected void onDestroy() { browser.destroy(); super.onDestroy(); }
}
