package de.arelorian.softwaregpu;

import android.app.Activity;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.view.View;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceError;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import android.net.Uri;

public final class MainActivity extends Activity {
    private WebView browser;
    private TextView status;
    private String permittedHost = "";
    private static final String PREFS = "are_gradio_endpoint";

    static boolean validEndpoint(String value) {
        if (value == null) return false;
        Uri uri = Uri.parse(value.trim());
        return "https".equalsIgnoreCase(uri.getScheme()) && uri.getHost() != null
            && !uri.getHost().isEmpty() && uri.getEncodedAuthority() != null && !uri.getEncodedAuthority().contains("@")
            && uri.getPort() <= 65535 && uri.getPort() >= -1;
    }
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setPadding(16, 16, 16, 16);
        status = new TextView(this);
        status.setText("ARE SoftwareGPU • HTTPS-Gradio-Server eingeben");
        EditText endpoint = new EditText(this);
        endpoint.setSingleLine(true);
        endpoint.setHint("https://gradio.example.org");
        endpoint.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        endpoint.setText(prefs.getString("endpoint", ""));
        Button connect = new Button(this);
        connect.setText("Verbinden");
        browser = new WebView(this);
        browser.getSettings().setJavaScriptEnabled(true);
        browser.getSettings().setDomStorageEnabled(true);
        browser.getSettings().setAllowFileAccess(false);
        browser.getSettings().setAllowContentAccess(false);
        browser.getSettings().setJavaScriptCanOpenWindowsAutomatically(false);
        browser.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri target = request.getUrl();
                return !("https".equalsIgnoreCase(target.getScheme()) && permittedHost.equalsIgnoreCase(target.getHost()));
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) status.setText("Server nicht erreichbar. HTTPS-Adresse prüfen.");
            }
        });
        connect.setOnClickListener(v -> {
            String url = endpoint.getText().toString().trim();
            if (!validEndpoint(url)) {
                status.setText("Nur vollständige HTTPS-Adressen ohne Benutzerinfo erlaubt.");
                return;
            }
            prefs.edit().putString("endpoint", url).apply();
            status.setText("Verbinde mit " + Uri.parse(url).getHost());
            permittedHost = Uri.parse(url).getHost();
            browser.loadUrl(url);
        });
        container.addView(status);
        container.addView(endpoint);
        container.addView(connect);
        container.addView(browser, new LinearLayout.LayoutParams(-1, 0, 1f));
        setContentView(container);
    }
    @Override public void onBackPressed() {
        if (browser.canGoBack()) browser.goBack(); else super.onBackPressed();
    }
    @Override protected void onDestroy() { browser.destroy(); super.onDestroy(); }
}
