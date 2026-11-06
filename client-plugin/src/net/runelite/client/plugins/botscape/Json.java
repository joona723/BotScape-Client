package net.runelite.client.plugins.botscape;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** A small JSON reader/writer: objects become Maps, arrays Lists, numbers Doubles. */
final class Json {
    private final String s;
    private int i;

    private Json(String s) {
        this.s = s;
    }

    static Object parse(String text) {
        Json json = new Json(text);
        json.ws();
        Object value = json.value();
        json.ws();
        return value;
    }

    private Object value() {
        char c = s.charAt(i);
        switch (c) {
            case '{':
                return object();
            case '[':
                return array();
            case '"':
                return string();
            case 't':
                i += 4;
                return Boolean.TRUE;
            case 'f':
                i += 5;
                return Boolean.FALSE;
            case 'n':
                i += 4;
                return null;
            default:
                return number();
        }
    }

    private Map<String, Object> object() {
        Map<String, Object> map = new LinkedHashMap<>();
        i++;
        ws();
        if (s.charAt(i) == '}') {
            i++;
            return map;
        }
        while (true) {
            ws();
            String key = string();
            ws();
            i++; // :
            ws();
            map.put(key, value());
            ws();
            if (s.charAt(i++) == '}') {
                return map;
            }
        }
    }

    private List<Object> array() {
        List<Object> list = new ArrayList<>();
        i++;
        ws();
        if (s.charAt(i) == ']') {
            i++;
            return list;
        }
        while (true) {
            ws();
            list.add(value());
            ws();
            if (s.charAt(i++) == ']') {
                return list;
            }
        }
    }

    private String string() {
        StringBuilder out = new StringBuilder();
        i++;
        while (true) {
            char c = s.charAt(i++);
            if (c == '"') {
                return out.toString();
            }
            if (c == '\\') {
                char e = s.charAt(i++);
                switch (e) {
                    case 'n' -> out.append('\n');
                    case 't' -> out.append('\t');
                    case 'r' -> out.append('\r');
                    case 'b' -> out.append('\b');
                    case 'f' -> out.append('\f');
                    case 'u' -> {
                        out.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                        i += 4;
                    }
                    default -> out.append(e);
                }
            } else {
                out.append(c);
            }
        }
    }

    private Double number() {
        int start = i;
        while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) {
            i++;
        }
        return Double.parseDouble(s.substring(start, i));
    }

    private void ws() {
        while (i < s.length() && Character.isWhitespace(s.charAt(i))) {
            i++;
        }
    }

    static String write(Map<String, ?> map) {
        StringBuilder out = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, ?> e : map.entrySet()) {
            if (!first) {
                out.append(',');
            }
            first = false;
            out.append(quote(e.getKey())).append(':');
            Object v = e.getValue();
            out.append(value(v));
        }
        return out.append('}').toString();
    }

    @SuppressWarnings("unchecked")
    private static String value(Object v) {
        if (v instanceof String str) {
            return quote(str);
        }
        if (v instanceof Map<?, ?> nested) {
            return write((Map<String, ?>) nested);
        }
        if (v instanceof Number n && n.doubleValue() == Math.rint(n.doubleValue()) && !Double.isInfinite(n.doubleValue())) {
            return String.valueOf(n.longValue());
        }
        return String.valueOf(v);
    }

    private static String quote(String text) {
        return '"' + text.replace("\\", "\\\\").replace("\"", "\\\"") + '"';
    }
}
