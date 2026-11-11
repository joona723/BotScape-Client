package net.runelite.client.plugins.botscape;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import javax.inject.Inject;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.events.GameStateChanged;
import net.runelite.api.events.VarbitChanged;
import net.runelite.client.callback.ClientThread;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;
import net.runelite.client.ui.ClientToolbar;
import net.runelite.client.ui.NavigationButton;
import net.runelite.client.util.LinkBrowser;

/**
 * Bot Scape: run scripts on your characters, make clones, see the family's shared bank and open
 * the live map from the client's toolbar. Data comes from the server's bot gateway.
 *
 * Started with -Dbotscape.login=name, the client logs in as that character on its own (the
 * password comes from bots/<main>/bot.env; clones use their main's password).
 */
@PluginDescriptor(
	name = "Bot Scape",
	description = "Scripts, your group, the shared bank and the live map",
	tags = {"bot", "scripts", "group", "members", "map"}
)
public class BotScapePlugin extends Plugin
{
	private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(BotScapePlugin.class);

	private static final String MAP_URL = Gateway.configBase() + "/map";

	@Inject
	private ClientToolbar clientToolbar;

	@Inject
	private net.runelite.client.ui.overlay.OverlayManager overlayManager;

	private BotMouseOverlay botMouse;

	@Inject
	private Client client;

	@Inject
	private ClientThread clientThread;

	@Inject
	private net.runelite.client.config.ConfigManager configManager;

	@Inject
	private net.runelite.client.plugins.PluginManager pluginManager;

	@Inject
	private net.runelite.client.ui.ClientUI clientUi;

	@Inject
	private net.runelite.client.input.KeyManager keyManager;

	/**
	 * The admin quest stepper (::quest active <name>): while it's on, the left and right arrow keys
	 * step the quest back and on instead of turning the camera. The server says it's on/off in chat
	 * ("[Quest stepper] ..."); the server only runs it for admins in the real client, never bots.
	 */
	private volatile boolean questStepper;

	private final net.runelite.client.input.KeyListener stepperKeys = new net.runelite.client.input.KeyListener()
	{
		@Override
		public void keyTyped(java.awt.event.KeyEvent e)
		{
			// User-requested: § opens the admin menu (only when the server says this player is an admin).
			if (e.getKeyChar() != '§' || client.getGameState() != GameState.LOGGED_IN || client.getLocalPlayer() == null)
			{
				return;
			}
			e.consume();
			java.awt.Window owner = javax.swing.SwingUtilities.getWindowAncestor(client.getCanvas());
			AdminMenu.toggle(owner, () -> client.getLocalPlayer() == null ? null : client.getLocalPlayer().getName());
		}

		@Override
		public void keyPressed(java.awt.event.KeyEvent e)
		{
			if (!questStepper || e.getModifiersEx() != 0 || client.getGameState() != GameState.LOGGED_IN)
			{
				return;
			}
			String step = e.getKeyCode() == java.awt.event.KeyEvent.VK_RIGHT ? "quest next"
				: e.getKeyCode() == java.awt.event.KeyEvent.VK_LEFT ? "quest prev" : null;
			if (step == null || client.getLocalPlayer() == null)
			{
				return;
			}
			e.consume();
			String name = client.getLocalPlayer().getName();
			new Thread(() ->
			{
				try
				{
					Gateway.post("/players/" + Gateway.enc(name) + "/command", java.util.Map.of("text", step));
				}
				catch (Exception ex)
				{
					log.warn("Bot Scape: quest stepper key failed", ex);
				}
			}, "botscape-quest-stepper").start();
		}

		@Override
		public void keyReleased(java.awt.event.KeyEvent e)
		{
		}
	};

	/*
	 * User-requested: staff see their crown by their own name in the chat input line too, like the account
	 * icons (group ironman...). The client only draws the account type there, so the plugin adds the crown:
	 * learned from the player's own public messages (the server puts it on them) and remembered per name.
	 */
	private String ownIcon;
	private int chatInputWidget = -1;

	private String ownIconKey(String name)
	{
		return "chatIcon." + name.toLowerCase();
	}

	private void decorateChatInput()
	{
		net.runelite.api.Player me = client.getLocalPlayer();
		if (me == null || me.getName() == null)
		{
			return;
		}
		if (ownIcon == null)
		{
			ownIcon = configManager.getConfiguration("botscape", ownIconKey(me.getName()));
			if (ownIcon == null)
			{
				return;
			}
		}
		String plain = me.getName() + ":";
		for (int child = chatInputWidget >= 0 ? chatInputWidget : 0; child < (chatInputWidget >= 0 ? chatInputWidget + 1 : 120); child++)
		{
			net.runelite.api.widgets.Widget w = client.getWidget(162, child);
			String text = w == null ? null : w.getText();
			if (text != null && text.startsWith(plain))
			{
				chatInputWidget = child;
				w.setText(ownIcon + text);
				return;
			}
			if (text != null && text.startsWith(ownIcon + plain))
			{
				chatInputWidget = child;
				return;
			}
		}
	}

	/** A "Lookup" on players (in the world): opens the Bot Scape hiscores on them. */
	@Subscribe
	public void onMenuEntryAdded(net.runelite.api.events.MenuEntryAdded event)
	{
		if (!"Trade with".equals(event.getOption()) || hiscores == null)
		{
			return;
		}
		String name = net.runelite.client.util.Text.removeTags(event.getTarget());
		int cut = name.indexOf("(level-");
		String target = (cut > 0 ? name.substring(0, cut) : name).trim();
		client.createMenuEntry(-1).setOption("Lookup").setTarget(event.getTarget())
			.setType(net.runelite.api.MenuAction.RUNELITE)
			.onClick(e -> javax.swing.SwingUtilities.invokeLater(() ->
			{
				clientToolbar.openPanel(hiscoreButton);
				hiscores.lookup(target);
			}));
	}

	@Subscribe
	public void onBeforeRender(net.runelite.api.events.BeforeRender event)
	{
		decorateChatInput();
	}

	@Subscribe
	public void onChatMessage(net.runelite.api.events.ChatMessage event)
	{
		// The player's own public message names them with their crown (<img=N>): remember it.
		net.runelite.api.Player me = client.getLocalPlayer();
		if (me != null && me.getName() != null && event.getName() != null
			&& (event.getType() == net.runelite.api.ChatMessageType.PUBLICCHAT || event.getType() == net.runelite.api.ChatMessageType.MODCHAT))
		{
			java.util.regex.Matcher m = java.util.regex.Pattern.compile("^(<img=[0-9]+>)(.*)$").matcher(event.getName());
			if (m.matches() && m.group(2).replace(' ', ' ').equalsIgnoreCase(me.getName().replace(' ', ' '))
				&& !m.group(1).equals(ownIcon))
			{
				ownIcon = m.group(1);
				configManager.setConfiguration("botscape", ownIconKey(me.getName()), ownIcon);
			}
		}
		String text = event.getMessage();
		if (text != null && text.contains("[Quest stepper]"))
		{
			questStepper = !(text.contains("off.") || text.contains("Stepper off"));
		}
	}

	/** Bring the window to the front once, when it first shows the login screen. */
	private boolean broughtToFront;

	private BotScapeData data;
	private ScriptsPanel scripts;
	private FamilyPanel family;
	private NavigationButton scriptsButton;
	private NavigationButton familyButton;
	private NavigationButton mapButton;
	private NavigationButton hiscoreButton;
	private HiscorePanel hiscores;
	@Inject
	private net.runelite.client.game.SkillIconManager skillIcons;
	/** Who this client plays as: -Dbotscape.login, else the main character. */
	private String loginName;
	/** Log in by itself at the next login screen: when the client starts and after a lost connection. */
	private boolean autoLogin = true;
	/** After a lost connection: keep trying (the server may be restarting) until logged in. */
	// Also on at start (user-reported): a client reopened by a hub update while the server was still
	// restarting tried once, failed and stayed on the login screen. It keeps trying until logged in.
	private boolean reconnecting = true;
	private int retries;

	@Override
	protected void startUp()
	{
		// No "Are you sure you want to exit?" box: turned off once, so a player can still turn it back on.
		if (configManager.getConfiguration("botscape", "exitWarningOff") == null)
		{
			configManager.setConfiguration("runelite", "warningOnExit", "NEVER");
			configManager.setConfiguration("botscape", "exitWarningOff", "true");
		}
		// User-requested defaults, set once (a player can still turn them off): the GPU plugin, and
		// Stretched Mode keeping the aspect ratio. Started now too, not only from the next launch.
		if (configManager.getConfiguration("botscape", "displayDefaults") == null)
		{
			configManager.setConfiguration("botscape", "displayDefaults", "true");
			configManager.setConfiguration("stretchedmode", "keepAspectRatio", "true");
			javax.swing.SwingUtilities.invokeLater(() ->
			{
				for (Plugin p : pluginManager.getPlugins())
				{
					String name = p.getClass().getSimpleName();
					if (!name.equals("GpuPlugin") && !name.equals("StretchedModePlugin"))
					{
						continue;
					}
					pluginManager.setPluginEnabled(p, true);
					try
					{
						pluginManager.startPlugin(p);
					}
					catch (Exception e)
					{
						// enabled in the config: it starts with the next launch
					}
				}
			});
		}
		titleTimer.start();
		Path root = Path.of(System.getProperty("botscape.root", ".")).toAbsolutePath().normalize();
		data = new BotScapeData(System.getProperty("botscape.main", "simba"), root);
		String login = System.getProperty("botscape.login");
		loginName = login == null || login.isBlank() ? data.main() : login.strip();
		scripts = new ScriptsPanel(data);
		family = new FamilyPanel(data);

		scriptsButton = NavigationButton.builder().tooltip("Scripts").icon(BotScapeUi.image("scripts", 16))
			.priority(0).panel(scripts).build();
		familyButton = NavigationButton.builder().tooltip("Bot Scape: your group and its bank")
			.icon(BotScapeUi.image("family", 16)).priority(1).panel(family).build();
		mapButton = NavigationButton.builder().tooltip("Live map").icon(BotScapeUi.image("map", 16)).priority(2)
			.onClick(() -> openMap(root)).build();
		clientToolbar.addNavigation(scriptsButton);
		clientToolbar.addNavigation(familyButton);
		clientToolbar.addNavigation(mapButton);
		// User-requested: the hiscore lookup from this server (RuneLite's own asks Jagex's hiscores).
		hiscores = new HiscorePanel(skillIcons);
		hiscoreButton = NavigationButton.builder().tooltip("Bot Scape hiscores").icon(BotScapeUi.image("hiscores", 16))
			.priority(3).panel(hiscores).build();
		clientToolbar.addNavigation(hiscoreButton);
		// RuneLite's own Hiscore plugin looks players up on Jagex's hiscores (user-reported 2026-11-11: the newly pulled
		// client showed those): off on every start, not just the first, so it can't come back.
		{
			javax.swing.SwingUtilities.invokeLater(() ->
			{
				for (Plugin p : pluginManager.getPlugins())
				{
					if (!p.getClass().getSimpleName().equals("HiscorePlugin"))
					{
						continue;
					}
					pluginManager.setPluginEnabled(p, false);
					try
					{
						pluginManager.stopPlugin(p);
					}
					catch (Exception e)
					{
						// disabled in the config: it stays off from the next launch
					}
				}
			});
		}
		keyManager.registerKeyListener(stepperKeys);
		botMouse = new BotMouseOverlay(client);
		overlayManager.add(botMouse);

		// The login screen often shows before plugins start, so wait for it here rather than relying
		// on the GameStateChanged event. Runs on the client thread until it returns true.
		clientThread.invokeLater(() ->
		{
			if (client.getGameState() == GameState.LOGGED_IN)
			{
				return true;
			}
			if (client.getGameState() != GameState.LOGIN_SCREEN)
			{
				return false;
			}
			loginScreen();
			return true;
		});
	}

	/**
	 * User-requested: the window title shows what the script is doing ("Bot Scape - Simba · Fishing:
	 * Shrimps +10 XP"). RuneLite sets its own title on login changes, so it's put back every 2 s.
	 */
	private final javax.swing.Timer titleTimer = new javax.swing.Timer(2000, e -> updateTitle());

	/**
	 * User-requested: each character's client opens where it was on the desktop. All clients share one
	 * RuneLite profile (one saved position), so the plugin keeps a position per character.
	 */
	private boolean boundsRestored;
	private String savedBounds;

	private void keepWindowPlace(java.awt.Frame frame)
	{
		// One file per character (the clients share RuneLite's settings, and each would overwrite the others').
		java.nio.file.Path file = Path.of(System.getProperty("botscape.root", ".")).toAbsolutePath().normalize()
			.resolve(".botscape-client").resolve("window-" + (loginName == null ? "main" : loginName.toLowerCase()) + ".txt");
		if (!boundsRestored)
		{
			boundsRestored = true;
			String saved = null;
			try
			{
				saved = Files.exists(file) ? Files.readString(file).strip() : null;
			}
			catch (IOException e)
			{
				// no saved place yet
			}
			if (saved != null)
			{
				try
				{
					String[] p = saved.split(",");
					java.awt.Rectangle r = new java.awt.Rectangle(Integer.parseInt(p[0]), Integer.parseInt(p[1]),
						Integer.parseInt(p[2]), Integer.parseInt(p[3]));
					boolean onScreen = false;
					for (java.awt.GraphicsDevice d : java.awt.GraphicsEnvironment.getLocalGraphicsEnvironment().getScreenDevices())
					{
						// At least the title bar on a connected screen (a monitor may be gone since).
						onScreen |= d.getDefaultConfiguration().getBounds().intersects(new java.awt.Rectangle(r.x, r.y, r.width, 40));
					}
					if (onScreen && (frame.getExtendedState() & java.awt.Frame.MAXIMIZED_BOTH) == 0)
					{
						frame.setBounds(r);
					}
					savedBounds = saved;
				}
				catch (RuntimeException e)
				{
					// a broken entry: the next save replaces it
				}
			}
			return;
		}
		if ((frame.getExtendedState() & (java.awt.Frame.MAXIMIZED_BOTH | java.awt.Frame.ICONIFIED)) != 0)
		{
			return;
		}
		java.awt.Rectangle b = frame.getBounds();
		String now = b.x + "," + b.y + "," + b.width + "," + b.height;
		if (!now.equals(savedBounds))
		{
			savedBounds = now;
			try
			{
				Files.createDirectories(file.getParent());
				Files.writeString(file, now);
			}
			catch (IOException e)
			{
				// tried again in 2 s
			}
		}
	}

	private void updateTitle()
	{
		java.awt.Window window = client.getCanvas() == null ? null : javax.swing.SwingUtilities.getWindowAncestor(client.getCanvas());
		if (!(window instanceof java.awt.Frame) || data == null)
		{
			return;
		}
		if (window.isShowing())
		{
			keepWindowPlace((java.awt.Frame) window);
		}
		net.runelite.api.Player me = client.getLocalPlayer();
		String name = me != null && me.getName() != null ? me.getName() : loginName;
		String doing = name == null ? "" : data.activity(name.toLowerCase());
		if (doing.length() > 70)
		{
			doing = doing.substring(0, 67) + "...";
		}
		String title = "BotScape" + (name != null ? " - " + name : "") + (doing.isEmpty() ? "" : " · " + doing);
		java.awt.Frame frame = (java.awt.Frame) window;
		if (!title.equals(frame.getTitle()))
		{
			frame.setTitle(title);
		}
	}

	@Override
	protected void shutDown()
	{
		titleTimer.stop();
		clientToolbar.removeNavigation(scriptsButton);
		clientToolbar.removeNavigation(familyButton);
		clientToolbar.removeNavigation(mapButton);
		clientToolbar.removeNavigation(hiscoreButton);
		keyManager.unregisterKeyListener(stepperKeys);
		overlayManager.remove(botMouse);
		botMouse.stop();
		scripts.shutdown();
		data.shutdown();
	}

	/** The chatbox item search's redraw (clientscript 751) and the procedure that draws it (752). */
	private static final int ITEM_SEARCH_UPDATE = 751;
	private static final int ITEM_SEARCH_DRAW = 752;
	/** chatbox:mes_layer_scrollcontents, where the search results are drawn. */
	private static final int ITEM_SEARCH_RESULTS = (162 << 16) | 51;

	/**
	 * The item search (Grand Exchange buy, ::spawn) shows each item's id under its name, so
	 * same-named copies in the cache can be told apart.
	 */
	@Subscribe
	public void onScriptPostFired(net.runelite.api.events.ScriptPostFired event)
	{
		if (event.getScriptId() != ITEM_SEARCH_UPDATE && event.getScriptId() != ITEM_SEARCH_DRAW)
		{
			return;
		}
		net.runelite.api.widgets.Widget results = client.getWidget(ITEM_SEARCH_RESULTS);
		if (results == null || results.getDynamicChildren() == null)
		{
			return;
		}
		net.runelite.api.widgets.Widget[] children = results.getDynamicChildren();
		for (net.runelite.api.widgets.Widget icon : children)
		{
			if (icon == null || icon.getItemId() <= 0)
			{
				continue;
			}
			for (net.runelite.api.widgets.Widget text : children)
			{
				if (text == null || text.getItemId() > 0 || text.getText() == null || text.getText().isEmpty()
					|| text.getOriginalY() != icon.getOriginalY()
					|| text.getText().contains("id " + icon.getItemId()))
				{
					continue;
				}
				// A name already on two lines gets the id on its second line so it fits the row.
				String id = "<col=9f9f9f>id " + icon.getItemId() + "</col>";
				String name = text.getText();
				text.setText(name.contains("<br>") ? name + " " + id : name + "<br>" + id);
			}
		}
	}

	// --- display settings the server doesn't keep -----------------------------------------------
	// The client flips these itself (Settings > Display, its own scripts) and never tells the
	// server, so they were back to off at every login (user-reported). The plugin remembers them and
	// puts them back after logging in.
	private static final int[] DISPLAY_VARBITS = {
		4609, // side_transparency: transparent side panel
		4608, // chatbox_transparency: transparent chatbox
	};
	private boolean restoring;
	/** False from login until the settings are restored: the server's own values aren't your choice. */
	private boolean settled;

	/*
	 * User-requested: while a script runs, the camera turns now and then for a nicer view: behind the
	 * character, looking the way it faces (at the fishing spot, the tree, the monster), slightly to the
	 * side and tilted, smoothly (the client's own camera easing). Moving the camera yourself pauses it
	 * for a minute.
	 */
	private final java.util.Random cameraRandom = new java.util.Random();
	private int cameraYawSet = -1;
	private long cameraNextAt;
	private long cameraPausedUntil;
	private int cameraFacing = -1;

	/** The smaller angle between two Jagex angles (0-2047), 0-1024. */
	private static int angleBetween(int a, int b)
	{
		int d = Math.abs(a - b) & 2047;
		return Math.min(d, 2048 - d);
	}

	@Subscribe
	public void onGameTick(net.runelite.api.events.GameTick event)
	{
		net.runelite.api.Player me = client.getLocalPlayer();
		if (me == null || data == null || me.getName() == null || data.activity(me.getName().toLowerCase()).isEmpty())
		{
			cameraYawSet = -1;
			return;   // only while a script runs
		}
		long now = System.currentTimeMillis();
		if (cameraYawSet >= 0 && angleBetween(client.getCameraYawTarget(), cameraYawSet) > 24)
		{
			// The camera target isn't where we left it: the player turned it. Hands off for a minute.
			cameraPausedUntil = now + 60_000;
			cameraYawSet = -1;
		}
		if (now < cameraPausedUntil)
		{
			return;
		}
		boolean busy = me.getAnimation() != -1 || me.getInteracting() != null;
		int facing = me.getOrientation();
		boolean turned = cameraFacing < 0 || angleBetween(facing, cameraFacing) > 300;
		if (!busy || (now < cameraNextAt && !turned))
		{
			return;
		}
		// Actor orientation counts from south; the camera looking the same way is half a turn round.
		int yaw = (facing + 1024 + cameraRandom.nextInt(361) - 180) & 2047;
		int pitch = 290 + cameraRandom.nextInt(80);
		client.setCameraYawTarget(yaw);
		client.setCameraPitchTarget(pitch);
		cameraYawSet = yaw;
		cameraFacing = facing;
		cameraNextAt = now + 20_000 + cameraRandom.nextInt(25_000);
	}

	@Subscribe
	public void onVarbitChanged(VarbitChanged event)
	{
		if (restoring || !settled || client.getGameState() != GameState.LOGGED_IN)
		{
			return;
		}
		for (int varbit : DISPLAY_VARBITS)
		{
			if (event.getVarbitId() == varbit)
			{
				configManager.setConfiguration("botscape", "varbit" + varbit, String.valueOf(event.getValue()));
			}
		}
	}

	private void restoreDisplaySettings()
	{
		// A few ticks after login, once the server has sent its values.
		settled = false;
		final int[] ticks = {0};
		clientThread.invokeLater(() ->
		{
			if (client.getGameState() != GameState.LOGGED_IN)
			{
				return true;
			}
			if (++ticks[0] < 100)
			{
				return false;
			}
			restoring = true;
			try
			{
				for (int varbit : DISPLAY_VARBITS)
				{
					String saved = configManager.getConfiguration("botscape", "varbit" + varbit);
					if (saved != null && client.getVarbitValue(varbit) != Integer.parseInt(saved))
					{
						client.setVarbit(varbit, Integer.parseInt(saved));
						log.info("Bot Scape: restored display setting varbit {} = {}", varbit, saved);
					}
				}
			}
			finally
			{
				restoring = false;
				settled = true;
			}
			return true;
		});
	}

	@Subscribe
	public void onGameStateChanged(GameStateChanged event)
	{
		switch (event.getGameState())
		{
			case LOGIN_SCREEN:
				loginScreen();
				break;
			case CONNECTION_LOST:
				// The server restarted or the connection dropped: log back in when it's possible.
				autoLogin = true;
				reconnecting = true;
				retries = 0;
				break;
			case LOGGED_IN:
				autoLogin = false;
				reconnecting = false;
				restoreDisplaySettings();
				break;
			default:
				break;
		}
	}

	/**
	 * RuneLite reopens at its last size; a window taller or wider than the screen (it once grew with a
	 * long script list) goes back to the default size, keeping your size when it already fits.
	 */
	private static final int DEFAULT_GAME_HEIGHT = 503;

	private void fitToScreen()
	{
		java.awt.Window window = javax.swing.SwingUtilities.getWindowAncestor(client.getCanvas());
		if (window == null || (window instanceof java.awt.Frame frame && (frame.getExtendedState() & java.awt.Frame.MAXIMIZED_BOTH) != 0))
		{
			return;
		}
		java.awt.GraphicsConfiguration screen = window.getGraphicsConfiguration();
		java.awt.Rectangle usable = screen.getBounds();
		java.awt.Insets taskbar = java.awt.Toolkit.getDefaultToolkit().getScreenInsets(screen);
		usable = new java.awt.Rectangle(usable.x + taskbar.left, usable.y + taskbar.top,
			usable.width - taskbar.left - taskbar.right, usable.height - taskbar.top - taskbar.bottom);
		java.awt.Rectangle now = window.getBounds();
		if (now.width <= usable.width && now.height <= usable.height && usable.contains(now))
		{
			return;
		}
		// Back to the default client size (user-requested): the game's 765x503 plus the sidebar, centred.
		java.awt.Insets frame = window.getInsets();
		int width = Math.min(now.width, usable.width);
		int height = Math.min(DEFAULT_GAME_HEIGHT + frame.top + frame.bottom, usable.height);
		int x = usable.x + (usable.width - width) / 2;
		int y = usable.y + (usable.height - height) / 2;
		window.setBounds(x, y, width, height);
		configManager.unsetConfiguration("runelite", "clientBounds");
		log.info("Bot Scape: client window was bigger than the screen, back to the default size ({}x{})", width, height);
	}

	/**
	 * The login screen always has this client's character and password filled in, so you never type
	 * them; it logs in by itself when the client starts and after a lost connection (after you log
	 * out yourself it only fills them in). Call on the client thread.
	 */
	private void loginScreen()
	{
		if (!broughtToFront)
		{
			// Windows opens programs started from another one behind it; RuneLite's forceFocus pops
			// the window in front (briefly always-on-top) so you don't have to click it.
			broughtToFront = true;
			javax.swing.SwingUtilities.invokeLater(() ->
			{
				fitToScreen();
				clientUi.forceFocus();
			});
		}
		String password = password(data.root(), data.main());
		if (password == null)
		{
			log.warn("Bot Scape: no PASSWORD in bots/{}/bot.env; can't log in as {}", data.main(), loginName);
			return;
		}
		client.setUsername(loginName);
		client.setPassword(password);
		if (autoLogin)
		{
			autoLogin = false; // One try; if it fails the fields stay filled for the Login button.
			log.info("Bot Scape: logging in as {}", loginName);
			client.setGameState(GameState.LOGGING_IN);
		}
		else if (reconnecting && retries < MAX_RETRIES)
		{
			// The login failed (server still restarting?): try again in a few seconds.
			retries++;
			long at = System.currentTimeMillis() + RETRY_MILLIS;
			clientThread.invokeLater(() ->
			{
				if (!reconnecting || client.getGameState() != GameState.LOGIN_SCREEN)
				{
					return client.getGameState() != GameState.LOGIN_SCREEN || !reconnecting;
				}
				if (System.currentTimeMillis() < at)
				{
					return false;
				}
				autoLogin = true;
				loginScreen();
				return true;
			});
		}
	}

	private static final int MAX_RETRIES = 180;   // 15 minutes: a server update takes about 5
	private static final long RETRY_MILLIS = 5000;

	private static String password(Path root, String main)
	{
		try
		{
			for (String line : Files.readAllLines(root.resolve("bots").resolve(main).resolve("bot.env")))
			{
				if (line.startsWith("PASSWORD="))
				{
					return line.substring("PASSWORD=".length()).strip();
				}
			}
		}
		catch (IOException e)
		{
			log.warn("Bot Scape: can't read bot.env", e);
		}
		return null;
	}

	private static void openMap(Path root)
	{
		Path edge = Path.of("C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe");
		try
		{
			if (Files.exists(edge))
			{
				new ProcessBuilder(edge.toString(), "--app=" + MAP_URL, "--window-size=1200,800",
					"--user-data-dir=" + root.resolve(".map-window")).start();
				return;
			}
		}
		catch (IOException e)
		{
			log.warn("Bot Scape: can't open Edge", e);
		}
		LinkBrowser.browse(MAP_URL);
	}
}
