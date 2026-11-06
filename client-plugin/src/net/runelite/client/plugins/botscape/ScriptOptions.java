package net.runelite.client.plugins.botscape;

import java.awt.Component;
import java.awt.GridLayout;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.swing.JCheckBox;
import javax.swing.JComponent;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JSpinner;
import javax.swing.SpinnerNumberModel;

/**
 * A script's options (its OPTIONS = {"name": ("label", default), ...}), asked for when you press
 * Run: a checkbox for True/False, a number field for whole numbers (level goals, kill counts). The
 * answers go in .options.json next to the script, which the script reads (sdk script_options) and
 * the launcher's script card shows too.
 */
final class ScriptOptions
{
	// "name": ("label", default). A label in double quotes may contain apostrophes (Cook's
	// Assistant); one in single quotes may contain double quotes.
	private static final Pattern OPTION = Pattern.compile(
		"[\"'](\\w+)[\"']\\s*:\\s*\\(\\s*(?:\"([^\"]*)\"|'([^']*)')\\s*,\\s*(True|False|-?\\d+)\\s*\\)");

	private record Option(String key, String label, Object fallback) {}

	private static final int MAX_HEIGHT = 480;

	private ScriptOptions() {}

	private static List<Option> declared(Path script)
	{
		List<Option> found = new ArrayList<>();
		try
		{
			String text = Files.readString(script, StandardCharsets.UTF_8);
			int start = text.indexOf("OPTIONS = {");
			if (start < 0)
			{
				return found;
			}
			int end = text.indexOf("\n}", start);
			Matcher m = OPTION.matcher(text.substring(start, end < 0 ? text.length() : end));
			while (m.find())
			{
				String v = m.group(4);
				String label = m.group(2) != null ? m.group(2) : m.group(3);
				Object fallback = v.equals("True") ? Boolean.TRUE : v.equals("False") ? Boolean.FALSE : (Object) Integer.parseInt(v);
				found.add(new Option(m.group(1), label, fallback));
			}
		}
		catch (Exception ignored)
		{
			// Unreadable or no options: run without asking.
		}
		return found;
	}

	@SuppressWarnings("unchecked")
	private static Map<String, Object> readAll(Path folder)
	{
		try
		{
			Object parsed = Json.parse(Files.readString(folder.resolve(".options.json"), StandardCharsets.UTF_8));
			if (parsed instanceof Map<?, ?> map)
			{
				return new LinkedHashMap<>((Map<String, Object>) map);
			}
		}
		catch (Exception ignored)
		{
			// No choices saved yet.
		}
		return new LinkedHashMap<>();
	}

	/** Asks for the script's options; false if the player cancelled (then don't run it). */
	@SuppressWarnings("unchecked")
	static boolean ask(Component parent, Path script)
	{
		List<Option> options = declared(script);
		if (options.isEmpty())
		{
			return true;
		}
		Map<String, Object> all = readAll(script.getParent());
		Map<String, Object> saved = all.get(script.getFileName().toString()) instanceof Map<?, ?> m
			? new LinkedHashMap<>((Map<String, Object>) m) : new LinkedHashMap<>();

		JPanel panel = new JPanel(new GridLayout(0, 1, 0, 6));
		Map<String, JComponent> fields = new LinkedHashMap<>();
		for (Option o : options)
		{
			Object value = saved.getOrDefault(o.key(), o.fallback());
			if (o.fallback() instanceof Boolean)
			{
				JCheckBox box = new JCheckBox(o.label(), Boolean.TRUE.equals(value) || "true".equals(String.valueOf(value)));
				fields.put(o.key(), box);
				panel.add(box);
			}
			else
			{
				int number;
				try
				{
					number = (int) Double.parseDouble(String.valueOf(value));
				}
				catch (NumberFormatException e)
				{
					number = (Integer) o.fallback();
				}
				JSpinner spinner = new JSpinner(new SpinnerNumberModel(Math.max(0, number), 0, 1_000_000, 1));
				JPanel row = new JPanel(new java.awt.BorderLayout(8, 0));
				row.add(spinner, java.awt.BorderLayout.WEST);
				row.add(new JLabel(o.label()), java.awt.BorderLayout.CENTER);
				fields.put(o.key(), spinner);
				panel.add(row);
			}
		}
		String name = script.getFileName().toString().replace(".py", "");
		// Many options (AIO has 26): scroll instead of growing past the screen.
		Component content = panel;
		if (panel.getPreferredSize().height > MAX_HEIGHT)
		{
			javax.swing.JScrollPane scroll = new javax.swing.JScrollPane(panel);
			scroll.setBorder(null);
			scroll.getVerticalScrollBar().setUnitIncrement(16);
			scroll.setPreferredSize(new java.awt.Dimension(panel.getPreferredSize().width + 24, MAX_HEIGHT));
			content = scroll;
		}
		int answer = JOptionPane.showConfirmDialog(parent, content, name + " options", JOptionPane.OK_CANCEL_OPTION,
			JOptionPane.PLAIN_MESSAGE);
		if (answer != JOptionPane.OK_OPTION)
		{
			return false;
		}
		for (Map.Entry<String, JComponent> e : fields.entrySet())
		{
			saved.put(e.getKey(), e.getValue() instanceof JCheckBox box ? (Object) box.isSelected()
				: (Object) ((Number) ((JSpinner) e.getValue()).getValue()).intValue());
		}
		all.put(script.getFileName().toString(), saved);
		try
		{
			Files.writeString(script.getParent().resolve(".options.json"), Json.write(all), StandardCharsets.UTF_8);
		}
		catch (Exception ignored)
		{
			// Couldn't save: the script still runs with its defaults.
		}
		return true;
	}
}
