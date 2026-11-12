package net.runelite.client.plugins.botscape;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.swing.SwingUtilities;
import javax.swing.Timer;

/** Polls the bot gateway every two seconds and tells the panels (on the Swing thread). */
class BotScapeData
{
	private final String main;
	private final Path root;
	private final ExecutorService io = Executors.newSingleThreadExecutor(r ->
	{
		Thread t = new Thread(r, "botscape-gateway");
		t.setDaemon(true);
		return t;
	});
	private final List<Runnable> listeners = new CopyOnWriteArrayList<>();
	private final Timer timer = new Timer(2000, e -> refresh());

	private volatile Map<String, String> status = Map.of();
	private volatile Map<String, Object> family = Map.of();
	private volatile Map<String, Object> familyState = Map.of();
	private volatile boolean offline = true;
	private volatile Map<String, Object> activities = Map.of();
	private volatile String foreign;
	private volatile String playing;

	BotScapeData(String main, Path root)
	{
		this.main = main.toLowerCase();
		this.root = root;
		Gateway.configure(root, this.main);
		timer.start();
		refresh();
	}

	String main()
	{
		return main;
	}

	Path root()
	{
		return root;
	}

	boolean offline()
	{
		return offline;
	}

	void addListener(Runnable listener)
	{
		listeners.add(listener);
	}

	String status(String name)
	{
		return status.getOrDefault(name, "offline");
	}

	Map<String, Object> family()
	{
		return family;
	}

	/** Snapshot of an online family member (for the shared bank), or empty. */
	Map<String, Object> familyState()
	{
		return familyState;
	}

	/** What a character's script last said it was doing, or "" (from the map server). */
	String activity(String name)
	{
		return Gateway.str(Gateway.map(activities.get(name)).get("text"));
	}

	List<String> characters()
	{
		List<String> names = new ArrayList<>();
		names.add(main);
		for (Object c : Gateway.list(family.get("clones")))
		{
			names.add(Gateway.str(Gateway.map(c).get("name")));
		}
		return names;
	}

	void post(String path)
	{
		io.submit(() ->
		{
			try
			{
				Gateway.post(path, null);
			}
			catch (Exception ignored)
			{
				// Server offline.
			}
			refresh();
		});
	}

	void refresh()
	{
		io.submit(() ->
		{
			try
			{
				Map<String, String> s = new HashMap<>();
				for (Object b : Gateway.list(Gateway.get("/bots")))
				{
					Map<String, Object> bot = Gateway.map(b);
					s.put(Gateway.str(bot.get("name")), Gateway.str(bot.get("status")));
				}
				for (Object p : Gateway.list(Gateway.get("/players")))
				{
					s.put(Gateway.str(p), "online");
				}
				Map<String, Object> fam = Gateway.map(Gateway.get("/families/" + Gateway.enc(main)));
				status = s;
				if (!fam.containsKey("error") && !fam.isEmpty())
				{
					family = fam;
				}
				Map<String, Object> state = Map.of();
				for (String name : characters())
				{
					if ("online".equals(s.get(name)))
					{
						state = Gateway.map(Gateway.map(Gateway.get("/players/" + Gateway.enc(name) + "/state")).get("state"));
						break;
					}
				}
				familyState = state;
				offline = false;
				try
				{
					activities = Gateway.map(Gateway.getUrl(Gateway.configBase() + "/api/activity"));   // the server's, not this PC's
				}
				catch (Exception e)
				{
					activities = Map.of();
				}
			}
			catch (Exception e)
			{
				offline = true;
			}
			String login = playing;
			if (login != null)
			{
				foreign = inGroup(login) ? null : login;
			}
			SwingUtilities.invokeLater(() -> listeners.forEach(Runnable::run));
		});
	}

	/**
	 * The character this client is logged in as when it isn't in the group the client was opened for, else null
	 * (user-reported 2026-11-12: logged in as Test11, the panels showed zazu's group and its scripts ran on zazu).
	 * The Scripts and Group panels stay off for it.
	 */
	String foreign()
	{
		return foreign;
	}

	/** The client logged in as [login] (the name typed at the login screen): checked off the client thread. */
	void loggedIn(String login)
	{
		playing = login;
		refresh();
	}

	void loggedOut()
	{
		playing = null;
		if (foreign != null)
		{
			foreign = null;
			SwingUtilities.invokeLater(() -> listeners.forEach(Runnable::run));
		}
	}

	/**
	 * Is [login] (the name typed at the login screen) one of this group's characters? Unknown (the group hasn't
	 * loaded, or this install has no sign-in at all) counts as yes: then there's nothing to mix up.
	 */
	boolean inGroup(String login)
	{
		if (login == null || login.isBlank() || family.isEmpty() || !Gateway.signedIn())
		{
			return true;
		}
		String name = login.strip().toLowerCase().replace('_', ' ');
		if (name.equals(main.replace('_', ' ')))
		{
			return true;
		}
		for (String key : new String[]{"clones", "members"})
		{
			for (Object o : Gateway.list(family.get(key)))
			{
				Map<String, Object> c = Gateway.map(o);
				for (String field : new String[]{"name", "display"})
				{
					if (Gateway.str(c.get(field)).toLowerCase().replace('_', ' ').equals(name))
					{
						return true;
					}
				}
			}
		}
		return false;
	}

	void shutdown()
	{
		timer.stop();
		io.shutdownNow();
	}
}
