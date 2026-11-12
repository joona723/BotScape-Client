package net.runelite.client.plugins.botscape;

import static net.runelite.client.plugins.botscape.BotScapeUi.GOLD;
import static net.runelite.client.plugins.botscape.BotScapeUi.GREEN;
import static net.runelite.client.plugins.botscape.BotScapeUi.GREEN_HOVER;
import static net.runelite.client.plugins.botscape.BotScapeUi.MUTED;
import static net.runelite.client.plugins.botscape.BotScapeUi.RED;
import static net.runelite.client.plugins.botscape.BotScapeUi.RED_HOVER;
import static net.runelite.client.plugins.botscape.BotScapeUi.TEXT;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.Dimension;
import java.awt.Font;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;
import javax.swing.BorderFactory;
import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.ScrollPaneConstants;
import javax.swing.JTextPane;
import javax.swing.SwingUtilities;
import javax.swing.Timer;
import javax.swing.text.BadLocationException;
import javax.swing.text.SimpleAttributeSet;
import javax.swing.text.StyleConstants;
import javax.swing.text.StyledDocument;
import net.runelite.client.ui.ColorScheme;
import net.runelite.client.ui.FontManager;
import net.runelite.client.ui.PluginPanel;

/** Scripts: one card per script in bots/<main>/, each with its own play/stop button, plus output. */
class ScriptsPanel extends PluginPanel
{
	private static final DateTimeFormatter TIME = DateTimeFormatter.ofPattern("HH:mm:ss");

	private final BotScapeData data;
	private final Path dir;
	/** Bot Scape's own script pack (ships with the game). */
	private final Path packDir;
	/** User-requested: scripts run on the character this client plays as (no picking). */
	private final javax.swing.JLabel character = new javax.swing.JLabel();
	private final BotScapeUi.Pill status = new BotScapeUi.Pill("offline", BotScapeUi.statusColor("offline"));
	private final JPanel cards = new JPanel();
	private final JTextPane output = new JTextPane();
	private final Map<String, Running> running = new HashMap<>();
	private final Timer ticker;

	private static final class Running
	{
		final String script;
		final Process process;
		final long started = System.currentTimeMillis();

		Running(String script, Process process)
		{
			this.script = script;
			this.process = process;
		}
	}

	ScriptsPanel(BotScapeData data)
	{
		// Not wrapped in a scroll pane: the panel is as tall as the sidebar, and the Output box below
		// the scripts takes all the height that's left (user-requested).
		super(false);
		this.data = data;
		this.dir = data.root().resolve("bots").resolve(data.main());
		this.packDir = data.root().resolve("scripts").resolve("botscape");
		setLayout(new BoxLayout(this, BoxLayout.Y_AXIS));
		setBorder(BorderFactory.createEmptyBorder(10, 10, 10, 10));

		JPanel top = new JPanel(new BorderLayout(6, 0));
		top.setOpaque(false);
		top.setAlignmentX(Component.LEFT_ALIGNMENT);
		top.add(BotScapeUi.bold("Scripts", GOLD), BorderLayout.WEST);
		javax.swing.JButton reload = BotScapeUi.iconButton("reload", 16, "Reload the scripts folder");
		reload.addActionListener(e -> loadScripts());
		top.add(reload, BorderLayout.EAST);
		top.setMaximumSize(new Dimension(Integer.MAX_VALUE, 28));
		add(top);
		add(Box.createVerticalStrut(8));

		JPanel who = new JPanel(new BorderLayout(6, 0));
		who.setOpaque(false);
		who.setAlignmentX(Component.LEFT_ALIGNMENT);
		character.setFont(FontManager.getRunescapeSmallFont());
		character.setText("Runs on " + selected());
		character.setForeground(java.awt.Color.LIGHT_GRAY);
		who.add(character, BorderLayout.CENTER);
		who.add(status, BorderLayout.EAST);
		who.setMaximumSize(new Dimension(Integer.MAX_VALUE, 26));
		add(who);
		add(Box.createVerticalStrut(10));

		cards.setLayout(new BoxLayout(cards, BoxLayout.Y_AXIS));
		cards.setOpaque(false);
		// The scripts scroll in their own box (a long list must never make the panel, and with it the
		// client window, taller); the Output box is below, with a divider you can drag between them.
		JPanel cardsHolder = new WidthTrackingPanel();
		cardsHolder.setOpaque(false);
		cardsHolder.add(cards, BorderLayout.NORTH);
		JScrollPane cardsScroll = new JScrollPane(cardsHolder, ScrollPaneConstants.VERTICAL_SCROLLBAR_AS_NEEDED,
			ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER);
		cardsScroll.setBorder(BorderFactory.createEmptyBorder());
		cardsScroll.getViewport().setOpaque(false);
		cardsScroll.setOpaque(false);
		cardsScroll.getVerticalScrollBar().setUnitIncrement(16);
		cardsScroll.setMinimumSize(new Dimension(PANEL_WIDTH, 80));
		cardsScroll.setPreferredSize(new Dimension(PANEL_WIDTH, 300));

		BotScapeUi.RoundButton clear = new BotScapeUi.RoundButton("Clear", ColorScheme.DARK_GRAY_COLOR,
			ColorScheme.DARK_GRAY_HOVER_COLOR);
		clear.setForeground(MUTED);
		clear.addActionListener(e -> output.setText(""));
		output.setEditable(false);
		output.setBackground(ColorScheme.DARKER_GRAY_COLOR);
		output.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 11));
		output.setBorder(BorderFactory.createEmptyBorder(6, 8, 6, 8));
		JScrollPane scroll = new JScrollPane(output);
		scroll.setBorder(BorderFactory.createEmptyBorder());
		JPanel outputBox = new JPanel(new BorderLayout(0, 4));
		outputBox.setOpaque(false);
		outputBox.add(BotScapeUi.header("Output", clear), BorderLayout.NORTH);
		outputBox.add(scroll, BorderLayout.CENTER);
		outputBox.setMinimumSize(new Dimension(PANEL_WIDTH, 100));
		outputBox.setPreferredSize(new Dimension(PANEL_WIDTH, 240));

		javax.swing.JSplitPane split = new javax.swing.JSplitPane(javax.swing.JSplitPane.VERTICAL_SPLIT, cardsScroll, outputBox);
		split.setResizeWeight(0.55);
		split.setBorder(BorderFactory.createEmptyBorder());
		split.setOpaque(false);
		split.setDividerSize(6);
		split.setContinuousLayout(true);
		split.setAlignmentX(Component.LEFT_ALIGNMENT);
		split.setPreferredSize(new Dimension(PANEL_WIDTH, 540));
		split.setMaximumSize(new Dimension(Integer.MAX_VALUE, Integer.MAX_VALUE));
		add(split);
		say(null, "Press ▶ on a script to run it on " + selected() + ".", MUTED);
		continueAfterUpdate();

		data.addListener(this::onData);
		loadScripts();
		ticker = new Timer(1000, e -> paintCards());
		ticker.start();
		pollHubScripts();
		// User-requested: new or edited scripts show up by themselves (the folders are checked every
		// 3 seconds and the cards rebuilt only when a .py file was added, removed or saved).
		watcher = new Timer(3000, e ->
		{
			String now = folderStamp();
			if (!now.equals(stamp))
			{
				loadScripts();
			}
		});
		watcher.start();
	}

	private final Timer watcher;
	private String stamp = "";

	// User-requested: a script a hub runs on this character shows here too. Polled off the Swing
	// thread every 3 s from the map server (hubs report what they run to /api/running).
	private volatile Map<String, Object> hubRunning = Map.of();
	private volatile Map<String, Object> activities = Map.of();

	/** This client in the running-scripts list: hubs show its scripts as "in the game client". */
	private static final String PC = hostName() + " game client:" + ProcessHandle.current().pid();

	private static String hostName()
	{
		try
		{
			return java.net.InetAddress.getLocalHost().getHostName();
		}
		catch (Exception e)
		{
			return "this PC";
		}
	}

	private void pollHubScripts()
	{
		Thread poller = new Thread(() ->
		{
			while (true)
			{
				try
				{
					// User-requested: stoppable from the hub or the client. Report ours; a stop the
					// hub asked for comes back in the answer.
					Map<String, Object> mine = new HashMap<>();
					for (Map.Entry<String, Running> e : new HashMap<>(running).entrySet())
					{
						if (e.getValue().process.isAlive())
						{
							mine.put(e.getKey().toLowerCase(), Map.of(
								"script", Path.of(e.getValue().script).getFileName().toString().replace(".py", ""),
								"started", e.getValue().started / 1000.0));
						}
					}
					Map<String, Object> answer = Gateway.map(Gateway.postUrl(Gateway.configBase() + "/api/running",
						Map.of("pc", PC, "scripts", mine)));
					for (Object name : Gateway.list(answer.get("stop")))
					{
						SwingUtilities.invokeLater(() ->
						{
							String who = running.keySet().stream().filter(k -> k.equalsIgnoreCase(Gateway.str(name)))
								.findFirst().orElse(null);
							if (who != null)
							{
								stop(who);
								say(who, "Stopped from the hub", MUTED);
							}
						});
					}
					Map<String, Object> all = new HashMap<>(Gateway.map(Gateway.getUrl(Gateway.configBase() + "/api/running")));
					all.values().removeIf(v -> PC.equals(Gateway.str(Gateway.map(v).get("pc"))));
					hubRunning = all;
					activities = Gateway.map(Gateway.getUrl(Gateway.configBase() + "/api/activity"));
				}
				catch (Exception e)
				{
					hubRunning = Map.of();
				}
				try
				{
					Thread.sleep(3000);
				}
				catch (InterruptedException e)
				{
					return;
				}
			}
		}, "botscape-hub-scripts");
		poller.setDaemon(true);
		poller.start();
	}

	/** The scripts folders' .py files with their sizes and save times: changes when any script does. */
	private String folderStamp()
	{
		StringBuilder out = new StringBuilder();
		for (Path folder : new Path[]{packDir, dir})
		{
			if (!Files.isDirectory(folder))
			{
				continue;
			}
			try (Stream<Path> files = Files.list(folder))
			{
				files.filter(f -> f.getFileName().toString().endsWith(".py")).sorted().forEach(f ->
				{
					try
					{
						out.append(f).append(':').append(Files.size(f)).append(':').append(Files.getLastModifiedTime(f).toMillis()).append(';');
					}
					catch (IOException ignored)
					{
						// Being saved right now: picked up on the next check.
					}
				});
			}
			catch (IOException ignored)
			{
				// Unreadable for a moment: try again next time.
			}
		}
		return out.toString();
	}

	void shutdown()
	{
		ticker.stop();
		watcher.stop();
		running.keySet().forEach(this::forget);
		running.values().forEach(r -> r.process.destroy());
	}

	// --- carrying a script over an update (user-requested) -----------------------------------
	// While a script runs, launcher/client-script-<who>.txt holds its path. A normal client close
	// or Stop deletes it; when the client was closed abruptly (the launcher's update closes it, or a
	// crash) it's still there, and the client continues that script once it's logged in again.

	private Path rememberFile(String who)
	{
		return data.root().resolve("launcher").resolve("client-script-" + who.toLowerCase() + ".txt");
	}

	private void remember(String who, String script)
	{
		try
		{
			Files.createDirectories(rememberFile(who).getParent());
			Files.writeString(rememberFile(who), script, StandardCharsets.UTF_8);
		}
		catch (IOException ignored)
		{
			// Not carried over then.
		}
	}

	private void forget(String who)
	{
		try
		{
			Files.deleteIfExists(rememberFile(who));
		}
		catch (IOException ignored)
		{
			// Nothing to forget.
		}
	}

	/** Does a hub (any PC) run a script on this character? Hubs report theirs to /api/running. */
	private static boolean runningElsewhere(String who)
	{
		try
		{
			return Gateway.map(Gateway.getUrl(Gateway.configBase() + "/api/running")).containsKey(who.toLowerCase());
		}
		catch (Exception e)
		{
			return false;
		}
	}

	/** At start: a script the client was running when it was closed abruptly carries on. */
	private void continueAfterUpdate()
	{
		String who = selected();
		String script;
		try
		{
			script = Files.readString(rememberFile(who), StandardCharsets.UTF_8).strip();
		}
		catch (IOException e)
		{
			return;
		}
		if (script.isEmpty() || !Files.exists(Path.of(script)))
		{
			forget(who);
			return;
		}
		String label = Path.of(script).getFileName().toString().replace(".py", "");
		say(who, label + " was running before the update: continuing once you're logged in", GOLD);
		Thread waiter = new Thread(() ->
		{
			for (int i = 0; i < 300; i++)    // up to 10 minutes for the client to log in
			{
				try
				{
					Thread.sleep(2000);
				}
				catch (InterruptedException e)
				{
					return;
				}
				if ("online".equals(data.status(who)) && !running.containsKey(who))
				{
					// User-reported: opening the client restarted its last script while the hub was
					// already running one on the character, and the two walked it back and forth.
					if (runningElsewhere(who))
					{
						forget(who);
						SwingUtilities.invokeLater(() -> say(who, label + " not continued: a script already plays " + who, MUTED));
						return;
					}
					SwingUtilities.invokeLater(() -> run(who, script));
					return;
				}
			}
		}, "botscape-continue-" + who);
		waiter.setDaemon(true);
		waiter.start();
	}

	private String selected()
	{
		return loginName();
	}

	/** Who this client plays as: -Dbotscape.login, else the main character. */
	private String loginName()
	{
		String login = System.getProperty("botscape.login");
		return login == null || login.isBlank() ? data.main() : login.strip();
	}

	private String shownForeign;

	private void onData()
	{
		if (!java.util.Objects.equals(shownForeign, data.foreign()))
		{
			shownForeign = data.foreign();
			paintCards();
		}
		String s = data.status(selected());
		status.set(s.equals("logging_in") ? "logging in" : s, BotScapeUi.statusColor(s));
		status.setToolTipText(data.activity(selected()).isEmpty() ? null : data.activity(selected()));
	}

	// --- script cards ------------------------------------------------------------------------

	private final List<String[]> scripts = new ArrayList<>();

	private void loadScripts()
	{
		stamp = folderStamp();
		scripts.clear();
		list(packDir, "pack");
		list(dir, "mine");
		paintCards();
	}

	/** Adds {file name, description, source, full path} for each script in a folder. */
	private void list(Path folder, String source)
	{
		if (!Files.isDirectory(folder))
		{
			return;
		}
		try (Stream<Path> files = Files.list(folder))
		{
			files.filter(p -> p.getFileName().toString().endsWith(".py"))
				.filter(p -> !p.getFileName().toString().equals("rs.py") && !p.getFileName().toString().startsWith("_"))
				.sorted((a, b) -> a.getFileName().toString().compareToIgnoreCase(b.getFileName().toString()))
				.forEach(p -> scripts.add(new String[]{p.getFileName().toString(), describe(p), source, p.toString()}));
		}
		catch (IOException e)
		{
			say(null, "Can't read scripts in " + folder, RED);
		}
	}

	/** The first line of a script's docstring, as its description. */
	private static String describe(Path script)
	{
		try
		{
			for (String line : Files.readAllLines(script, StandardCharsets.UTF_8))
			{
				String t = line.strip().replace("\"\"\"", "").strip();
				if (!t.isEmpty() && !t.startsWith("#"))
				{
					return t;
				}
			}
		}
		catch (IOException ignored)
		{
			// Unreadable script: no description.
		}
		return "";
	}

	private void paintCards()
	{
		cards.removeAll();
		if (data.foreign() != null)
		{
			cards.add(BotScapeUi.small("<html><div style='width:170px'>You're playing <b>" + BotScapeUi.esc(data.foreign()) + "</b>. This client was opened for "
				+ BotScapeUi.esc(data.main()) + "'s group, so its scripts stay off. To use them for " + BotScapeUi.esc(data.foreign())
				+ ", open the hub signed in as that character and start the client from there.</div></html>", MUTED));
			cards.revalidate();
			cards.repaint();
			return;
		}
		String who = selected();
		Running current = running.get(who);
		if (current != null && !current.process.isAlive())
		{
			running.remove(who);
			current = null;
		}
		String section = null;
		for (String[] script : scripts)
		{
			if (!script[2].equals(section))
			{
				section = script[2];
				cards.add(heading(section.equals("pack") ? "Bot Scape scripts" : "My scripts"));
			}
			String name = script[0];
			boolean isRunning = current != null && current.script.equals(script[3]);
			Map<String, Object> hub = current == null ? Gateway.map(hubRunning.get(who.toLowerCase())) : Map.of();
			if (!isRunning && name.replace(".py", "").equals(Gateway.str(hub.get("script"))))
			{
				cards.add(hubCard(script, hub));
			}
			else
			{
				cards.add(card(script, isRunning, isRunning ? current.started : 0));
			}
			cards.add(Box.createVerticalStrut(6));
		}
		if (!"mine".equals(section))
		{
			cards.add(heading("My scripts"));
			cards.add(BotScapeUi.small("<html><div style='width:170px'>Your own .py scripts go in bots/" + data.main()
				+ " (start from MyFirstScript.py).</div></html>", MUTED));
		}
		cards.revalidate();
		cards.repaint();
	}

	private Component heading(String title)
	{
		JLabel label = BotScapeUi.label(title, GOLD, FontManager.getRunescapeBoldFont());
		label.setBorder(javax.swing.BorderFactory.createEmptyBorder(8, 2, 4, 0));
		label.setAlignmentX(Component.LEFT_ALIGNMENT);
		return label;
	}

	/** A script a hub runs on this character: shown running, stopped from the hub that runs it. */
	private Component hubCard(String[] script, Map<String, Object> hub)
	{
		BotScapeUi.Card card = new BotScapeUi.Card();
		card.setAccent(GREEN);
		JPanel text = new JPanel();
		text.setLayout(new BoxLayout(text, BoxLayout.Y_AXIS));
		text.setOpaque(false);
		text.add(BotScapeUi.label(script[0].replace(".py", ""), TEXT, FontManager.getRunescapeBoldFont()));
		long started = (long) (hub.get("started") instanceof Number ? ((Number) hub.get("started")).doubleValue() * 1000 : 0);
		long secs = started > 0 ? Math.max(0, (System.currentTimeMillis() - started) / 1000) : 0;
		text.add(BotScapeUi.small(String.format("Running in the hub · %d:%02d:%02d", secs / 3600, secs / 60 % 60, secs % 60),
			new Color(0x5fd38d)));
		String doing = Gateway.str(Gateway.map(activities.get(selected().toLowerCase())).get("text"));
		if (doing != null && !doing.isBlank())
		{
			String shown = doing.length() > 90 ? doing.substring(0, 87) + "..." : doing;
			text.add(BotScapeUi.small("<html><div style='width:120px'>" + escapeHtml(shown) + "</div></html>", TEXT));
		}
		card.add(text, BorderLayout.CENTER);
		// Stops it in the hub that runs it (it picks the request up within a few seconds).
		javax.swing.JButton stop = BotScapeUi.iconButton("stop", 24, "Stop " + script[0].replace(".py", "") + " in the hub");
		String who = selected();
		stop.addActionListener(e -> new Thread(() ->
		{
			try
			{
				Gateway.postUrl(Gateway.configBase() + "/api/stop", Map.of("name", who.toLowerCase()));
				SwingUtilities.invokeLater(() -> say(who, "Asked the hub to stop it", MUTED));
			}
			catch (Exception ex)
			{
				SwingUtilities.invokeLater(() -> say(who, "Couldn't reach the server to stop it", MUTED));
			}
		}, "botscape-stop-hub").start());
		JPanel right = new JPanel(new BorderLayout());
		right.setOpaque(false);
		right.add(stop, BorderLayout.NORTH);
		card.add(right, BorderLayout.EAST);
		return card;
	}

	private Component card(String[] script, boolean isRunning, long started)
	{
		String name = script[0];
		String description = script[1];
		BotScapeUi.Card card = new BotScapeUi.Card();
		card.setAccent(isRunning ? GREEN : null);

		JPanel text = new JPanel();
		text.setLayout(new BoxLayout(text, BoxLayout.Y_AXIS));
		text.setOpaque(false);
		text.add(BotScapeUi.label(name.replace(".py", ""), TEXT, FontManager.getRunescapeBoldFont()));
		if (isRunning)
		{
			long secs = (System.currentTimeMillis() - started) / 1000;
			text.add(BotScapeUi.small(String.format("Running · %d:%02d:%02d", secs / 3600, secs / 60 % 60, secs % 60),
				new Color(0x5fd38d)));
			// What it's doing: the script's latest line of output (user-requested).
			String doing = lastLine.get(selected());
			if (doing != null && !doing.isBlank())
			{
				String shown = doing.length() > 90 ? doing.substring(0, 87) + "..." : doing;
				text.add(BotScapeUi.small("<html><div style='width:120px'>" + escapeHtml(shown) + "</div></html>", TEXT));
			}
		}
		else if (!description.isEmpty())
		{
			JLabel d = BotScapeUi.small("<html><div style='width:120px'>" + description + "</div></html>", MUTED);
			text.add(d);
		}
		card.add(text, BorderLayout.CENTER);

		javax.swing.JButton action = isRunning
			? BotScapeUi.iconButton("stop", 24, "Stop " + name)
			: BotScapeUi.iconButton("play", 24, "Run " + name + " on " + selected());
		action.addActionListener(e ->
		{
			if (isRunning)
			{
				stop(selected());
			}
			else if (hubRunning.containsKey(selected().toLowerCase()))
			{
				// Two scripts on one character walk it back and forth (user-reported).
				say(selected(), "The hub already runs " + Gateway.str(Gateway.map(hubRunning.get(selected().toLowerCase())).get("script"))
					+ " on " + selected() + ": stop it there first", GOLD);
			}
			else if (ScriptOptions.ask(this, Path.of(script[3])))
			{
				run(selected(), script[3]);
			}
		});
		JPanel right = new JPanel(new BorderLayout());
		right.setOpaque(false);
		right.add(action, BorderLayout.NORTH);
		card.add(right, BorderLayout.EAST);
		return card;
	}

	// --- running -----------------------------------------------------------------------------

	private void run(String who, String script)
	{
		if (data.foreign() != null)
		{
			say(null, "Not while you're playing " + data.foreign() + ": this client's scripts are for " + data.main() + "'s group.", RED);
			return;
		}
		stop(who);
		// The install's own Python (players may not have one on PATH), else the system's.
		Path root = Path.of(System.getProperty("botscape.root", ".")).toAbsolutePath().normalize();
		Path bundled = root.resolve("runtime").resolve("python").resolve("python.exe");
		String python = java.nio.file.Files.exists(bundled) ? bundled.toString() : "python";
		ProcessBuilder pb = new ProcessBuilder(python, "-u", script, who, "--main", data.main())
			.directory(dir.toFile())
			.redirectErrorStream(true);
		// The server this client plays on (not 127.0.0.1), and this client's sign-in, as the hub does.
		pb.environment().put("BOT_GATEWAY", Gateway.base());
		pb.environment().put("BOT_ACTIVITY", Gateway.configBase() + "/api/activity");
		String token = Gateway.token();
		if (token != null)
		{
			pb.environment().put("BOT_TOKEN", token);
		}
		pb.environment().put("BOT_MAIN", data.main().toLowerCase());
		pb.environment().put("RS_BOT", who.toLowerCase());
		pb.environment().put("PYTHONIOENCODING", "utf-8");
		String label = Path.of(script).getFileName().toString().replace(".py", "");
		try
		{
			Process proc = pb.start();
			running.put(who, new Running(script, proc));
			remember(who, script);
			say(who, label + " started", GOLD);
			Thread reader = new Thread(() ->
			{
				boolean lost = false;
				try (BufferedReader in = new BufferedReader(new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8)))
				{
					String line;
					while ((line = in.readLine()) != null)
					{
						String l = line;
						lost = lost || SERVER_GONE.matcher(l).find();
						Color color = l.contains("Traceback") || l.contains("Error") || l.startsWith("Stopped")
							? RED : TEXT;
						SwingUtilities.invokeLater(() -> say(who, l, color));
					}
				}
				catch (IOException ignored)
				{
					// Process ended.
				}
				int code;
				try
				{
					code = proc.waitFor();
				}
				catch (InterruptedException e)
				{
					code = 0;
				}
				// Not stopped by hand (Stop takes it out of `running` first), ended with an error and the
				// server went away: carry on once it's back (user-requested, for server restarts).
				Running still = running.get(who);
				boolean dropped = still != null && still.process == proc && code != 0 && (lost || !serverUp());
				if (still != null && still.process == proc)
				{
					running.remove(who);
					if (!dropped)
					{
						forget(who);
					}
				}
				SwingUtilities.invokeLater(() ->
				{
					say(who, label + " stopped", MUTED);
					if (dropped)
					{
						say(who, "The server went away: " + label + " continues when it's back", GOLD);
						resumeWhenBack(who, script);
					}
					paintCards();
				});
			}, "botscape-script-" + who);
			reader.setDaemon(true);
			reader.start();
		}
		catch (IOException e)
		{
			say(who, "Could not start Python: " + e.getMessage(), RED);
		}
		paintCards();
	}

	/** Scrolls up and down only: always as wide as the sidebar (cards wrap instead of being cut off). */
	private static final class WidthTrackingPanel extends JPanel implements javax.swing.Scrollable
	{
		WidthTrackingPanel()
		{
			super(new BorderLayout());
		}

		@Override
		public Dimension getPreferredScrollableViewportSize()
		{
			return getPreferredSize();
		}

		@Override
		public int getScrollableUnitIncrement(java.awt.Rectangle visible, int orientation, int direction)
		{
			return 16;
		}

		@Override
		public int getScrollableBlockIncrement(java.awt.Rectangle visible, int orientation, int direction)
		{
			return visible.height;
		}

		@Override
		public boolean getScrollableTracksViewportWidth()
		{
			return true;
		}

		@Override
		public boolean getScrollableTracksViewportHeight()
		{
			return false;
		}
	}

	private static final java.util.regex.Pattern SERVER_GONE = java.util.regex.Pattern.compile(
		"not reachable|WinError 1006[01]|ConnectionReset|RemoteDisconnected|Connection aborted|Connection refused|timed out|server is offline",
		java.util.regex.Pattern.CASE_INSENSITIVE);

	/** Scripts waiting for the server to come back (character -> script path). */
	private final Map<String, String> resume = new java.util.concurrent.ConcurrentHashMap<>();

	private static boolean serverUp()
	{
		try
		{
			Gateway.get("/players");
			return true;
		}
		catch (Exception e)
		{
			return false;
		}
	}

	/** Checks every 5 seconds; once the server has answered for 20 seconds, starts the script again. */
	private void resumeWhenBack(String who, String script)
	{
		resume.put(who, script);
		Thread waiter = new Thread(() ->
		{
			long backSince = 0;
			while (resume.get(who) != null && resume.get(who).equals(script))
			{
				try
				{
					Thread.sleep(5000);
				}
				catch (InterruptedException e)
				{
					return;
				}
				if (!serverUp())
				{
					backSince = 0;
					continue;
				}
				if (backSince == 0)
				{
					backSince = System.currentTimeMillis();
				}
				if (System.currentTimeMillis() - backSince >= 20_000 && resume.remove(who, script))
				{
					SwingUtilities.invokeLater(() ->
					{
						say(who, "The server is back: continuing", GOLD);
						run(who, script);
					});
					return;
				}
			}
		}, "botscape-resume-" + who);
		waiter.setDaemon(true);
		waiter.start();
	}

	private void stop(String who)
	{
		resume.remove(who);
		forget(who);
		Running r = running.remove(who);
		if (r != null && r.process.isAlive())
		{
			r.process.descendants().forEach(ProcessHandle::destroy);
			r.process.destroy();
			// Hand the character back: a server-side bot logs out, an attached script lets go.
			data.post("/bots/" + Gateway.enc(who) + "/logout");
		}
		paintCards();
	}

	/** Each character's latest script output line (shown on its running script's card). */
	private final Map<String, String> lastLine = new java.util.concurrent.ConcurrentHashMap<>();

	private static String escapeHtml(String text)
	{
		return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
	}

	private void say(String who, String line, Color color)
	{
		if (who != null && line != null && !line.isBlank() && !line.startsWith("Travel:"))
		{
			lastLine.put(who, line.strip());
		}
		StyledDocument doc = output.getStyledDocument();
		try
		{
			SimpleAttributeSet time = new SimpleAttributeSet();
			StyleConstants.setForeground(time, new Color(0x6a6a6a));
			doc.insertString(doc.getLength(), LocalTime.now().format(TIME) + " ", time);
			if (who != null)
			{
				SimpleAttributeSet name = new SimpleAttributeSet();
				StyleConstants.setForeground(name, who.equals(data.main()) ? GOLD : new Color(0x5fb3f0));
				StyleConstants.setBold(name, true);
				doc.insertString(doc.getLength(), who + " ", name);
			}
			SimpleAttributeSet body = new SimpleAttributeSet();
			StyleConstants.setForeground(body, color);
			doc.insertString(doc.getLength(), line + "\n", body);
			if (doc.getLength() > 60_000)
			{
				doc.remove(0, 20_000);
			}
		}
		catch (BadLocationException ignored)
		{
			// Never happens for appends.
		}
		output.setCaretPosition(doc.getLength());
	}
}
