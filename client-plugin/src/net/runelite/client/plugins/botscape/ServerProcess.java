package net.runelite.client.plugins.botscape;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PipedInputStream;
import java.io.PipedOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;

/**
 * A Bot Scape script that runs inside the game server (a server-side .kt version, like the hub's and the website's):
 * shaped like a Process so the Scripts panel runs, shows and stops it like a Python one. Started with the gateway's
 * POST /bots/{name}/serverbot; its output is the run's log lines (polled); destroy() stops it on the server.
 * Exit 9: it handed over to the Python script (the panel runs that instead).
 */
final class ServerProcess extends Process
{
	static final int HANDS_OVER = 9;

	private final String path;
	private final PipedInputStream output = new PipedInputStream(1 << 16);
	private final PipedOutputStream sink;
	private final CountDownLatch done = new CountDownLatch(1);
	private volatile int exit = -1;
	private volatile boolean stopping;

	/** Starts [script] for [who]; throws with the server's reason when it won't. */
	ServerProcess(String who, String script, String main, String password, List<String> args) throws IOException
	{
		this.path = "/bots/" + Gateway.enc(who.toLowerCase());
		this.sink = new PipedOutputStream(output);
		Map<String, Object> answer;
		try
		{
			answer = Gateway.map(Gateway.post(path + "/serverbot", Map.of("script", script, "minutes", 24 * 60, "main", main,
				"password", password == null ? "" : password, "args", args)));
		}
		catch (Exception e)
		{
			throw new IOException("the server didn't answer: " + e.getMessage());
		}
		if (!answer.containsKey("started"))
		{
			throw new IOException(Gateway.str(answer.getOrDefault("error", "the server didn't start " + script)));
		}
		Thread follower = new Thread(this::follow, "botscape-serverbot-" + who);
		follower.setDaemon(true);
		follower.start();
	}

	/** The run's lines, every 2 seconds, until it ends (15 misses in a row: the server went away). */
	private void follow()
	{
		long since = 0;
		int misses = 0;
		try
		{
			while (exit < 0)
			{
				try
				{
					Thread.sleep(2000);
				}
				catch (InterruptedException e)
				{
					break;
				}
				Map<String, Object> answer;
				try
				{
					answer = Gateway.map(Gateway.get(path + "/serverbot?since=" + since));
				}
				catch (Exception e)
				{
					answer = Map.of();
				}
				if (answer.isEmpty() || !answer.containsKey("running"))
				{
					if (++misses >= 15)
					{
						write("Stopped: lost the game server (not reachable)");
						exit = 1;
					}
					continue;
				}
				misses = 0;
				for (Object line : Gateway.list(answer.get("lines")))
				{
					Map<String, Object> l = Gateway.map(line);
					since = Math.max(since, ((Number) l.getOrDefault("id", 0)).longValue());
					write(Gateway.str(l.get("text")));
				}
				if (!Boolean.TRUE.equals(answer.get("running")))
				{
					Object code = answer.get("exit");
					exit = code instanceof Number n ? n.intValue() : (stopping ? 0 : 1);
				}
			}
		}
		finally
		{
			try
			{
				sink.close();
			}
			catch (IOException ignored)
			{
				// Already closed.
			}
			done.countDown();
		}
	}

	private void write(String line)
	{
		try
		{
			sink.write((line + "\n").getBytes(StandardCharsets.UTF_8));
			sink.flush();
		}
		catch (IOException ignored)
		{
			// Nobody reads the output any more.
		}
	}

	@Override
	public InputStream getInputStream()
	{
		return output;
	}

	@Override
	public InputStream getErrorStream()
	{
		return InputStream.nullInputStream();
	}

	@Override
	public OutputStream getOutputStream()
	{
		return OutputStream.nullOutputStream();
	}

	@Override
	public int waitFor() throws InterruptedException
	{
		done.await();
		return exit;
	}

	@Override
	public boolean waitFor(long timeout, TimeUnit unit) throws InterruptedException
	{
		return done.await(timeout, unit);
	}

	@Override
	public int exitValue()
	{
		if (done.getCount() > 0)
		{
			throw new IllegalThreadStateException("still running on the server");
		}
		return exit;
	}

	@Override
	public boolean isAlive()
	{
		return done.getCount() > 0;
	}

	/** Stops it on the server (its run says so in the output, then it ends). */
	@Override
	public void destroy()
	{
		stopping = true;
		try
		{
			Gateway.post(path + "/serverbot_stop", Map.of());
		}
		catch (Exception ignored)
		{
			// Server gone: the follower notices and ends it.
		}
	}

	@Override
	public Stream<ProcessHandle> descendants()
	{
		return Stream.empty();   // nothing runs on this PC
	}
}
