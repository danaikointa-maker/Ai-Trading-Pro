//+------------------------------------------------------------------+
//|                                              No7BridgeEA.mq5     |
//|  No7 AI Trading Pro — EA bridge client (MetaTrader 5)            |
//|                                                                  |
//|  The Advisor is the OUTBOUND half of the bridge: it polls the    |
//|  No7 API on a timer, executes exactly what it is handed, and     |
//|  reports the outcome once. The server never holds MT5            |
//|  credentials and never connects inbound.                         |
//|                                                                  |
//|  Contract (see services/api_gateway/routes/bridge.py):           |
//|    POST /api/bridge/register  {account_id, session_id, terminal, |
//|                                symbols}   + Bearer token         |
//|    POST /api/bridge/poll      {session_id, snapshot, results}    |
//|                                                                  |
//|  Rules the EA must keep, or the safety story is a lie:           |
//|   1. Execute a command id at most ONCE. Remember the ids you     |
//|      executed (g_last_ids) and skip them even if the server       |
//|      repeats one after a lost response.                          |
//|   2. Report the result on the NEXT poll, then forget it.         |
//|   3. Never invent prices: the snapshot is the terminal's own     |
//|      SymbolInfoTick(), and rates come from CopyRates().          |
//|   4. If register/poll fails, do not trade — wait and re-register.|
//|                                                                  |
//|  UNTESTED IN THIS REPOSITORY: MQL5 needs a Windows terminal to   |
//|  compile. The wire protocol is pinned by tests/test_bridge.py     |
//|  and exercised by scripts/run_bridge_sim.py; this file matches    |
//|  that protocol line for line, but it has not been compiled or    |
//|  run against a live broker. Treat the first demo run as a test.  |
//+------------------------------------------------------------------+
#property copyright "No7 AI Trading Pro"
#property version   "1.00"
#property strict
#property description "Polls the No7 API, executes orders/close/modify, reports back."

//--- inputs -------------------------------------------------------------
input string InpServerUrl   = "http://127.0.0.1:8000";  // API base (no trailing slash)
input string InpToken       = "";                        // bridge token (from server config)
input string InpAccountId   = "mt5-bridge-demo";         // must match bridge account
input string InpSymbols     = "XAUUSD";                  // comma separated
input int    InpPollMs      = 1000;                      // poll interval
input int    InpRatesBars   = 60;                        // M1 bars to push (0 = none)
input int    InpMagic       = 70707;                     // magic number for our orders
input int    InpSlippage    = 20;                        // deviation, in points
input bool   InpVerbose     = true;

//--- state --------------------------------------------------------------
string   g_session = "";
string   g_symbols[];
datetime g_last_poll = 0;
string   g_pending_ids[];      // executed, result not yet delivered
string   g_pending_json[];     // the json body for each pending result
string   g_executed_ids[];     // ids ever executed here — never run twice
int      g_generation = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(StringLen(InpToken) == 0)
     {
      Print("No7BridgeEA: InpToken is empty — the server will refuse the bridge. Aborting.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(StringLen(InpServerUrl) == 0 || StringFind(InpServerUrl, "http") != 0)
     {
      Print("No7BridgeEA: InpServerUrl must start with http:// or https://");
      return(INIT_PARAMETERS_INCORRECT);
     }
   SplitSymbols(InpSymbols);
   if(ArraySize(g_symbols) == 0)
     {
      Print("No7BridgeEA: no symbols configured");
      return(INIT_PARAMETERS_INCORRECT);
     }
   // One EA per account: the server keeps a single session per account id.
   if(!Register())
      return(INIT_FAILED);
   EventSetMillisecondTimer(MathMax(250, InpPollMs));
   PrintFormat("No7BridgeEA: registered session %s (%d symbols, poll %d ms)",
               g_session, ArraySize(g_symbols), InpPollMs);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTimer()
  {
   if(StringLen(g_session) == 0)
     {
      Register();
      return;
     }
   Poll();
  }

//+------------------------------------------------------------------+
//| helpers                                                          |
//+------------------------------------------------------------------+
void SplitSymbols(const string csv)
  {
   string parts[];
   int n = StringSplit(csv, ',', parts);
   ArrayResize(g_symbols, 0);
   for(int i = 0; i < n; i++)
     {
      string s = parts[i];
      StringTrimLeft(s);
      StringTrimRight(s);
      StringToUpper(s);
      if(StringLen(s) > 0)
        {
         int size = ArraySize(g_symbols);
         ArrayResize(g_symbols, size + 1);
         g_symbols[size] = s;
        }
     }
  }

bool AlreadyExecuted(const string id)
  {
   for(int i = 0; i < ArraySize(g_executed_ids); i++)
      if(g_executed_ids[i] == id)
         return(true);
   return(false);
  }

void RememberExecuted(const string id)
  {
   int size = ArraySize(g_executed_ids);
   ArrayResize(g_executed_ids, size + 1);
   g_executed_ids[size] = id;
   // keep the last 200 ids; a repeat older than that is already expired server-side
   if(ArraySize(g_executed_ids) > 200)
     {
      for(int i = 1; i < ArraySize(g_executed_ids); i++)
         g_executed_ids[i - 1] = g_executed_ids[i];
      ArrayResize(g_executed_ids, 199);
     }
  }

//+------------------------------------------------------------------+
//| HTTP                                                             |
//+------------------------------------------------------------------+
bool HttpPost(const string path, const string body, string &response, int &status_code)
  {
   string url = InpServerUrl + path;
   // Every bridge call carries the token: register checks it, and poll checks it again
   // because a poll can inject quotes and acknowledge orders.
   string headers = "Content-Type: application/json\r\n";
   headers += "Authorization: Bearer " + InpToken + "\r\n";

   char data[], result[];
   StringToCharArray(body, data, 0, StringLen(body), CP_UTF8);
   string result_headers;
   ResetLastError();
   status_code = -1;
   // WebRequest must be allowed for this URL: Tools -> Options -> Expert Advisors ->
   // "Allow WebRequest for listed URL" and add InpServerUrl.
   int code = WebRequest("POST", url, headers, 5000, data, result, result_headers);
   if(code == -1)
     {
      PrintFormat("No7BridgeEA: WebRequest failed (%d). Add %s to the allowed URLs "
                  "(Tools > Options > Expert Advisors).", GetLastError(), InpServerUrl);
      return(false);
     }
   status_code = code;
   response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   return(true);
  }

//+------------------------------------------------------------------+
//| register                                                         |
//+------------------------------------------------------------------+
bool Register()
  {
   string symbols_json = "[";
   for(int i = 0; i < ArraySize(g_symbols); i++)
     {
      if(i > 0)
         symbols_json += ",";
      symbols_json += "\"" + g_symbols[i] + "\"";
     }
   symbols_json += "]";

   string body = StringFormat(
                    "{\"account_id\":\"%s\",\"session_id\":\"%s\","
                    "\"terminal\":{\"build\":%d,\"company\":\"%s\",\"name\":\"No7BridgeEA\"},"
                    "\"symbols\":%s}",
                    InpAccountId, g_session, TerminalInfoInteger(TERMINAL_BUILD),
                    TerminalInfoString(TERMINAL_COMPANY), symbols_json);

   string response;
   int status = 0;
   if(!HttpPost("/api/bridge/register", body, response, status))
      return(false);
   if(status != 200)
     {
      PrintFormat("No7BridgeEA: register refused (%d): %s", status, response);
      return(false);
     }
   string session = JsonString(response, "session_id");
   if(StringLen(session) == 0)
     {
      Print("No7BridgeEA: register response has no session_id: ", response);
      return(false);
     }
   g_session = session;
   g_generation = (int)JsonNumber(response, "generation");
   // A restart means the server dropped everything the old session had queued: any
   // pending result we still hold belongs to a session that no longer exists.
   ArrayResize(g_pending_ids, 0);
   ArrayResize(g_pending_json, 0);
   return(true);
  }

//+------------------------------------------------------------------+
//| poll: send snapshot + pending results, receive commands          |
//+------------------------------------------------------------------+
void Poll()
  {
   string results = "[";
   for(int i = 0; i < ArraySize(g_pending_ids); i++)
     {
      if(i > 0)
         results += ",";
      results += g_pending_json[i];
     }
   results += "]";

   string body = StringFormat("{\"session_id\":\"%s\",\"snapshot\":%s,\"results\":%s}",
                              g_session, BuildSnapshot(), results);

   string response;
   int status = 0;
   if(!HttpPost("/api/bridge/poll", body, response, status))
      return;
   if(status == 409)
     {
      Print("No7BridgeEA: session superseded (409) — re-registering");
      g_session = "";
      Register();
      return;
     }
   if(status != 200)
     {
      PrintFormat("No7BridgeEA: poll failed (%d): %s", status, response);
      return;
     }

   // Delivered: our results are now the server's, so stop resending them.
   ArrayResize(g_pending_ids, 0);
   ArrayResize(g_pending_json, 0);

   string expired = JsonArrayRaw(response, "expired_unacked");
   if(StringLen(expired) > 2)
      Print("No7BridgeEA: WARNING commands expired before we acked them — check the "
            "terminal: ", expired);

   string commands = JsonArrayRaw(response, "commands");
   ProcessCommands(commands);
  }

//+------------------------------------------------------------------+
//| snapshot: account, quotes, symbol specs, positions, M1 rates     |
//+------------------------------------------------------------------+
string BuildSnapshot()
  {
   //--- account
   string account = StringFormat(
                       "\"account\":{\"login\":\"%I64d\",\"balance\":%.2f,\"equity\":%.2f,"
                       "\"margin\":%.2f,\"free_margin\":%.2f,\"currency\":\"%s\",\"leverage\":%d,"
                       "\"server\":\"%s\"}",
                       AccountInfoInteger(ACCOUNT_LOGIN),
                       AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY),
                       AccountInfoDouble(ACCOUNT_MARGIN), AccountInfoDouble(ACCOUNT_MARGIN_FREE),
                       AccountInfoString(ACCOUNT_CURRENCY),
                       (int)AccountInfoInteger(ACCOUNT_LEVERAGE),
                       AccountInfoString(ACCOUNT_SERVER));

   //--- quotes + specs
   string quotes = "\"quotes\":{";
   string specs = "\"symbols\":{";
   for(int i = 0; i < ArraySize(g_symbols); i++)
     {
      string sym = g_symbols[i];
      if(!SymbolSelect(sym, true))
         continue;
      MqlTick tick;
      if(!SymbolInfoTick(sym, tick))
         continue;
      double point = SymbolInfoDouble(sym, SYMBOL_POINT);
      if(i > 0)
        {
         quotes += ",";
         specs += ",";
        }
      quotes += StringFormat(
                   "\"%s\":{\"t\":%I64d,\"bid\":%.*f,\"ask\":%.*f,\"last\":%.*f}",
                   sym, (long)tick.time, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS), tick.bid,
                   (int)SymbolInfoInteger(sym, SYMBOL_DIGITS), tick.ask,
                   (int)SymbolInfoInteger(sym, SYMBOL_DIGITS), tick.last);
      specs += StringFormat(
                  "\"%s\":{\"digits\":%d,\"point\":%.*f,\"contract_size\":%.2f,\"min_lot\":%.2f,"
                  "\"max_lot\":%.2f,\"lot_step\":%.2f,\"stops_level_points\":%.0f,"
                  "\"spread_typical_points\":%.0f,\"tick_size\":%.*f}",
                  sym, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS), 8, point,
                  SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE),
                  SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN),
                  SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX),
                  SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP),
                  (double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL),
                  (double)((tick.ask - tick.bid) / (point > 0 ? point : 1)),
                  (int)SymbolInfoInteger(sym, SYMBOL_DIGITS), SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE));
     }
   quotes += "}";
   specs += "}";

   //--- positions
   string positions = "\"positions\":[";
   int total = PositionsTotal();
   bool first = true;
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!PositionSelectByTicket(ticket))
         continue;
      long magic = PositionGetInteger(POSITION_MAGIC);
      string comment = PositionGetString(POSITION_COMMENT);
      // Only our own trades: another EA's positions must never be adopted or closed.
      if(magic != InpMagic && StringFind(comment, "no7") < 0)
         continue;
      long type = PositionGetInteger(POSITION_TYPE);
      if(!first)
         positions += ",";
      first = false;
      positions += StringFormat(
                      "{\"ticket\":\"%I64u\",\"symbol\":\"%s\",\"direction\":\"%s\","
                      "\"volume\":%.2f,\"price_open\":%.*f,\"sl\":%.*f,\"tp\":%.*f,"
                      "\"time\":%I64d,\"price_current\":%.*f,\"profit\":%.2f,\"comment\":\"%s\"}",
                      ticket, PositionGetString(POSITION_SYMBOL),
                      (type == POSITION_TYPE_BUY ? "buy" : "sell"),
                      PositionGetDouble(POSITION_VOLUME),
                      (int)SymbolInfoInteger(PositionGetString(POSITION_SYMBOL), SYMBOL_DIGITS),
                      PositionGetDouble(POSITION_PRICE_OPEN),
                      (int)SymbolInfoInteger(PositionGetString(POSITION_SYMBOL), SYMBOL_DIGITS),
                      PositionGetDouble(POSITION_SL),
                      (int)SymbolInfoInteger(PositionGetString(POSITION_SYMBOL), SYMBOL_DIGITS),
                      PositionGetDouble(POSITION_TP),
                      (long)PositionGetInteger(POSITION_TIME),
                      (int)SymbolInfoInteger(PositionGetString(POSITION_SYMBOL), SYMBOL_DIGITS),
                      PositionGetDouble(POSITION_PRICE_CURRENT),
                      PositionGetDouble(POSITION_PROFIT), comment);
     }
   positions += "]";

   //--- M1 rates (analysis/backtest on the server side)
   string rates = "\"rates\":{";
   if(InpRatesBars > 0)
     {
      for(int i = 0; i < ArraySize(g_symbols); i++)
        {
         string sym = g_symbols[i];
         MqlRates bars[];
         int copied = CopyRates(sym, PERIOD_M1, 0, InpRatesBars, bars);
         if(copied <= 0)
            continue;
         if(i > 0)
            rates += ",";
         rates += "\"" + sym + "\":{\"M1\":[";
         for(int j = 0; j < copied; j++)
           {
            if(j > 0)
               rates += ",";
            rates += StringFormat("{\"t\":%I64d,\"o\":%.5f,\"h\":%.5f,\"l\":%.5f,\"c\":%.5f,\"v\":%I64d}",
                                  (long)bars[j].time, bars[j].open, bars[j].high, bars[j].low,
                                  bars[j].close, bars[j].tick_volume);
           }
         rates += "]}";
        }
     }
   rates += "}";

   return StringFormat("{\"server_time\":%I64d,%s,%s,%s,%s,%s,%s}",
                       (long)TimeTradeServer(), account, quotes, specs, positions, rates,
                       "\"terminal\":{\"build\":" + IntegerToString(TerminalInfoInteger(TERMINAL_BUILD)) + "}");
  }

//+------------------------------------------------------------------+
//| command execution                                                |
//+------------------------------------------------------------------+
void ProcessCommands(const string commands)
  {
   // Minimal JSON scanning: each command object carries "id" and "kind", and the
   // payload is re-read by the same keys. A full parser is deliberately avoided —
   // this runs on a 1-second timer inside the terminal.
   int cursor = 0;
   while(true)
     {
      int start = StringFind(commands, "{", cursor);
      if(start < 0)
         break;
      int end = MatchingBrace(commands, start);
      if(end < 0)
         break;
      string object = StringSubstr(commands, start, end - start + 1);
      cursor = end + 1;

      string id = JsonString(object, "id");
      string kind = JsonString(object, "kind");
      if(StringLen(id) == 0 || StringLen(kind) == 0)
         continue;
      if(AlreadyExecuted(id))
        {
         if(InpVerbose)
            PrintFormat("No7BridgeEA: skipping %s — already executed here", id);
         continue;
        }
      RememberExecuted(id);
      string outcome = ExecuteCommand(kind, object);
      AppendResult(id, outcome);
     }
  }

int MatchingBrace(const string text, const int open_pos)
  {
   int depth = 0;
   bool in_string = false;
   for(int i = open_pos; i < StringLen(text); i++)
     {
      ushort ch = StringGetCharacter(text, i);
      if(ch == '"')
         in_string = !in_string;
      else
         if(!in_string && ch == '{')
            depth++;
         else
            if(!in_string && ch == '}')
              {
               depth--;
               if(depth == 0)
                  return(i);
              }
     }
   return(-1);
  }

void AppendResult(const string id, const string outcome_json)
  {
   int size = ArraySize(g_pending_ids);
   ArrayResize(g_pending_ids, size + 1);
   ArrayResize(g_pending_json, size + 1);
   g_pending_ids[size] = id;
   g_pending_json[size] = "{\"id\":\"" + id + "\"," + outcome_json + "}";
   // Delivered on the next poll; a second copy is harmless (the server de-duplicates).
   if(size > 20)
     {
      for(int i = 1; i <= size; i++)
        {
         g_pending_ids[i - 1] = g_pending_ids[i];
         g_pending_json[i - 1] = g_pending_json[i];
        }
      ArrayResize(g_pending_ids, size);
      ArrayResize(g_pending_json, size);
     }
  }

string ExecuteCommand(const string kind, const string command)
  {
   if(kind == "ping")
      return("\"ok\":true,\"status\":\"pong\"");
   if(kind == "order")
      return(DoOrder(command));
   if(kind == "close")
      return(DoClose(command));
   if(kind == "modify")
      return(DoModify(command));
   return("\"ok\":false,\"error\":\"unknown kind " + kind + "\"");
  }

string DoOrder(const string command)
  {
   string symbol = JsonString(command, "symbol");
   string side = JsonString(command, "side");
   double volume = JsonNumber(command, "volume");
   double sl = JsonNumber(command, "sl");
   double tp = JsonNumber(command, "tp");

   if(!SymbolSelect(symbol, true))
      return("\"ok\":false,\"error\":\"unknown symbol " + symbol + "\"");

   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
      return("\"ok\":false,\"error\":\"no tick for " + symbol + "\"");

   bool is_buy = (side == "buy" || side == "up" || side == "long");
   MqlTradeRequest request;
   MqlTradeResult result;
   ZeroMemory(request);
   ZeroMemory(result);
   request.action = TRADE_ACTION_DEAL;
   request.symbol = symbol;
   request.volume = NormalizeVolume(symbol, volume);
   request.type = is_buy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   request.price = is_buy ? tick.ask : tick.bid;
   request.sl = sl;
   request.tp = tp;
   request.deviation = InpSlippage;
   request.magic = InpMagic;
   request.comment = "no7 bridge";
   request.type_filling = FillingMode(symbol);

   if(!OrderSend(request, result))
      return(StringFormat("\"ok\":false,\"error\":\"OrderSend failed %d: %s\",\"retcode\":%d",
                          GetLastError(), result.comment, (int)result.retcode));
   if(result.retcode != TRADE_RETCODE_DONE && result.retcode != TRADE_RETCODE_PLACED)
      return(StringFormat("\"ok\":false,\"error\":\"retcode %d %s\",\"retcode\":%d",
                          (int)result.retcode, result.comment, (int)result.retcode));

   if(InpVerbose)
      PrintFormat("No7BridgeEA: filled order %I64u %s %.2f %s @ %.5f", result.order,
                  (is_buy ? "buy" : "sell"), request.volume, symbol, result.price);
   return StringFormat("\"ok\":true,\"status\":\"filled\",\"ticket\":\"%I64u\","
                       "\"price\":%.5f,\"volume\":%.2f,\"retcode\":%d,\"message\":\"%s\"",
                       result.order, result.price, result.volume, (int)result.retcode,
                       result.comment);
  }

string DoClose(const string command)
  {
   string ticket_text = JsonString(command, "ticket");
   ulong ticket = (ulong)StringToInteger(ticket_text);
   if(ticket == 0 || !PositionSelectByTicket(ticket))
      return("\"ok\":false,\"error\":\"no such position " + ticket_text + "\"");
   string symbol = PositionGetString(POSITION_SYMBOL);
   double volume = PositionGetDouble(POSITION_VOLUME);
   double requested = JsonNumber(command, "volume");
   if(requested > 0 && requested < volume)
      volume = requested;
   bool is_buy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
   MqlTick tick;
   SymbolInfoTick(symbol, tick);

   MqlTradeRequest request;
   MqlTradeResult result;
   ZeroMemory(request);
   ZeroMemory(result);
   request.action = TRADE_ACTION_DEAL;
   request.position = ticket;
   request.symbol = symbol;
   request.volume = NormalizeVolume(symbol, volume);
   request.type = is_buy ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.price = is_buy ? tick.bid : tick.ask;
   request.deviation = InpSlippage;
   request.magic = InpMagic;
   request.comment = "no7 bridge close";
   request.type_filling = FillingMode(symbol);

   if(!OrderSend(request, result) || result.retcode != TRADE_RETCODE_DONE)
      return(StringFormat("\"ok\":false,\"error\":\"close failed %d %s\",\"retcode\":%d",
                          GetLastError(), result.comment, (int)result.retcode));
   if(InpVerbose)
      PrintFormat("No7BridgeEA: closed %I64u %.2f %s @ %.5f", ticket, request.volume, symbol,
                  result.price);
   return StringFormat("\"ok\":true,\"status\":\"closed\",\"ticket\":\"%I64u\","
                       "\"price\":%.5f,\"volume\":%.2f,\"retcode\":%d",
                       ticket, result.price, request.volume, (int)result.retcode);
  }

string DoModify(const string command)
  {
   string ticket_text = JsonString(command, "ticket");
   ulong ticket = (ulong)StringToInteger(ticket_text);
   if(ticket == 0 || !PositionSelectByTicket(ticket))
      return("\"ok\":false,\"error\":\"no such position " + ticket_text + "\"");
   double sl = JsonNumber(command, "sl");
   double tp = JsonNumber(command, "tp");
   if(sl <= 0)
      sl = PositionGetDouble(POSITION_SL);
   if(tp <= 0)
      tp = PositionGetDouble(POSITION_TP);

   MqlTradeRequest request;
   MqlTradeResult result;
   ZeroMemory(request);
   ZeroMemory(result);
   request.action = TRADE_ACTION_SLTP;
   request.position = ticket;
   request.symbol = PositionGetString(POSITION_SYMBOL);
   request.sl = sl;
   request.tp = tp;
   request.magic = InpMagic;

   if(!OrderSend(request, result) || result.retcode != TRADE_RETCODE_DONE)
      return(StringFormat("\"ok\":false,\"error\":\"modify failed %d %s\",\"retcode\":%d",
                          GetLastError(), result.comment, (int)result.retcode));
   return StringFormat("\"ok\":true,\"status\":\"modified\",\"ticket\":\"%I64u\"", ticket);
  }

double NormalizeVolume(const string symbol, const double volume)
  {
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double minimum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maximum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double out = (step > 0) ? MathRound(volume / step) * step : volume;
   out = MathMax(minimum, MathMin(maximum, out));
   return(NormalizeDouble(out, 2));
  }

ENUM_ORDER_TYPE_FILLING FillingMode(const string symbol)
  {
   long mode = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   // Symbols differ (IOC / FOK / RETURN); ask the terminal instead of assuming.
   if((mode & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      return(ORDER_FILLING_FOK);
   if((mode & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      return(ORDER_FILLING_IOC);
   return(ORDER_FILLING_RETURN);
  }

//+------------------------------------------------------------------+
//| tiny JSON readers (enough for this protocol, nothing more)       |
//+------------------------------------------------------------------+
string JsonString(const string json, const string key)
  {
   string needle = "\"" + key + "\":\"";
   int pos = StringFind(json, needle);
   if(pos < 0)
      return("");
   int start = pos + StringLen(needle);
   int end = StringFind(json, "\"", start);
   if(end < 0)
      return("");
   return(StringSubstr(json, start, end - start));
  }

double JsonNumber(const string json, const string key)
  {
   string needle = "\"" + key + "\":";
   int pos = StringFind(json, needle);
   if(pos < 0)
      return(0.0);
   int start = pos + StringLen(needle);
   int end = start;
   while(end < StringLen(json))
     {
      ushort ch = StringGetCharacter(json, end);
      if((ch >= '0' && ch <= '9') || ch == '-' || ch == '+' || ch == '.' || ch == 'e' || ch == 'E')
         end++;
      else
         break;
     }
   if(end == start)
      return(0.0);
   return(StringToDouble(StringSubstr(json, start, end - start)));
  }

string JsonArrayRaw(const string json, const string key)
  {
   string needle = "\"" + key + "\":[";
   int pos = StringFind(json, needle);
   if(pos < 0)
      return("[]");
   int start = pos + StringLen(needle) - 1;
   int depth = 0;
   for(int i = start; i < StringLen(json); i++)
     {
      ushort ch = StringGetCharacter(json, i);
      if(ch == '[')
         depth++;
      else
         if(ch == ']')
           {
            depth--;
            if(depth == 0)
               return(StringSubstr(json, start, i - start + 1));
           }
     }
   return("[]");
  }
//+------------------------------------------------------------------+
