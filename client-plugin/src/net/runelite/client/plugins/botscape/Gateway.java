package net.runelite.client.plugins.botscape;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;

/** Talks to the server's bot gateway (http://127.0.0.1:7780). */
final class Gateway {
    private static final String BASE = System.getProperty("botscape.gateway", "http://127.0.0.1:7780");
    private static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();

    private static java.nio.file.Path root = java.nio.file.Path.of(".");
    private static String main = "simba";
    private static volatile String token;

    private Gateway() {}

    /** The gateway's address, for the scripts this client starts (their BOT_GATEWAY). */
    static String base() {
        return BASE;
    }

    /** The client config server on the same host (live map, activity): port 8080. */
    static String configBase() {
        URI uri = URI.create(BASE);
        return uri.getScheme() + "://" + uri.getHost() + ":8080";
    }

    /** This client's sign-in, signed in first if needed (null on the host, which uses its admin key). */
    static String token() {
        authorize(HttpRequest.newBuilder(URI.create(BASE + "/players")));
        return token;
    }

    /** Where bots/<main>/bot.env and (on the host) the server's admin key are. */
    static void configure(java.nio.file.Path root, String main) {
        Gateway.root = root;
        Gateway.main = main;
        token = null;
    }

    /** The host uses the server's admin key; a player signs in with their own character. */
    private static HttpRequest.Builder authorize(HttpRequest.Builder builder) {
        java.nio.file.Path adminKey = root.resolve("rsmod").resolve(".data").resolve("gateway-admin.key");
        try {
            if (java.nio.file.Files.exists(adminKey)) {
                return builder.header("X-Admin-Key", java.nio.file.Files.readString(adminKey).strip());
            }
            if (token == null) {
                String password = null;
                for (String line : java.nio.file.Files.readAllLines(root.resolve("bots").resolve(main).resolve("bot.env"))) {
                    if (line.startsWith("PASSWORD=")) {
                        password = line.substring(9).strip();
                    }
                }
                if (password != null) {
                    HttpRequest req = HttpRequest.newBuilder(URI.create(BASE + "/auth"))
                            .timeout(Duration.ofSeconds(10))
                            .header("Content-Type", "application/json")
                            .POST(HttpRequest.BodyPublishers.ofString(Json.write(Map.of("name", main, "password", password))))
                            .build();
                    String t = str(map(Json.parse(HTTP.send(req, HttpResponse.BodyHandlers.ofString()).body())).get("token"));
                    token = t.isEmpty() ? null : t;
                }
            }
        } catch (Exception ignored) {
            // Offline or no credentials: the call goes out unsigned and fails with 401.
        }
        return token == null ? builder : builder.header("Authorization", "Bearer " + token);
    }

    static Object get(String path) throws Exception {
        HttpRequest req = authorize(HttpRequest.newBuilder(URI.create(BASE + path)).timeout(Duration.ofSeconds(5))).GET().build();
        return Json.parse(HTTP.send(req, HttpResponse.BodyHandlers.ofString()).body());
    }

    /** GET from another local service, e.g. the map server's /api/activity on port 8080. */
    static Object getUrl(String url) throws Exception {
        HttpRequest req = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(3)).GET().build();
        return Json.parse(HTTP.send(req, HttpResponse.BodyHandlers.ofString()).body());
    }

    /** A POST to any url (the map server's /api/running and /api/stop). */
    static Object postUrl(String url, Map<String, ?> body) throws Exception {
        HttpRequest req = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(3))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(Json.write(body))).build();
        return Json.parse(HTTP.send(req, HttpResponse.BodyHandlers.ofString()).body());
    }

    static Object post(String path, Map<String, ?> body) throws Exception {
        HttpRequest req = authorize(HttpRequest.newBuilder(URI.create(BASE + path)))
                .timeout(Duration.ofSeconds(15))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body == null ? "" : Json.write(body)))
                .build();
        return Json.parse(HTTP.send(req, HttpResponse.BodyHandlers.ofString()).body());
    }

    static String enc(String name) {
        return URLEncoder.encode(name, StandardCharsets.UTF_8).replace("+", "%20");
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> map(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : Map.of();
    }

    @SuppressWarnings("unchecked")
    static List<Object> list(Object o) {
        return o instanceof List ? (List<Object>) o : List.of();
    }

    static int num(Object o) {
        return o instanceof Number n ? n.intValue() : 0;
    }

    static String str(Object o) {
        return o == null ? "" : o.toString();
    }
}
