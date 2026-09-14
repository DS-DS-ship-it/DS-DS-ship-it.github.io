/*
 * MVX MeshBridge 3.1.1 Browser Compatibility Layer
 *
 * Browser -> native MeshBridge HTTP/HTTPS API
 *
 * Native ports:
 *
 *   UDP discovery : 49152
 *   Mesh TCP      : 49153
 *   HTTP API      : 49154
 *   HTTPS API     : 49155
 *
 * This adapter deliberately keeps the browser UI independent
 * from the native MeshBridge implementation.
 */

(() => {
    "use strict";

    const HTTP_LOCAL =
        "http://127.0.0.1:49154";

    const HTTPS_LOCAL =
        "https://127.0.0.1:49155";

    const DEFAULT_BASE =
        location.protocol === "https:"
            ? HTTPS_LOCAL
            : HTTP_LOCAL;

    const CONFIG = {
        requestTimeout: 7000,
        pollInterval: 1500,
        detailInterval: 2500,
        maxRows: 250
    };

    const state = {
        version: "3.1.1-browser",

        base: DEFAULT_BASE,

        connected: false,
        online: false,

        status: null,
        node: null,

        neighbors: [],
        routes: [],
        sessions: [],
        messages: [],
        packets: [],
        discovery: [],

        topology: {
            nodes: [],
            edges: []
        },

        events: [],

        lastError: null,
        lastUpdate: 0,

        eventSource: null,

        timers: [],

        diagnostics: {
            pageProtocol:
                location.protocol,

            pageOrigin:
                location.origin,

            securePage:
                location.protocol === "https:",

            attempted: [],

            selected:
                null
        }
    };

    const subscribers =
        new Set();

    function normalizeBase(value) {
        return String(
            value || DEFAULT_BASE
        )
        .trim()
        .replace(/\/+$/, "");
    }

    function getBase() {
        try {
            return normalizeBase(
                window.MVX_MESHBRIDGE_BASE ||
                localStorage.getItem(
                    "mvx_meshbridge_base"
                ) ||
                DEFAULT_BASE
            );
        } catch (_) {
            return DEFAULT_BASE;
        }
    }

    function saveBase(value) {
        try {
            localStorage.setItem(
                "mvx_meshbridge_base",
                value
            );
        } catch (_) {}
    }

    function emit(type, data) {
        try {
            window.dispatchEvent(
                new CustomEvent(
                    "mvx:" + type,
                    {
                        detail: data
                    }
                )
            );
        } catch (_) {}

        for (const fn of subscribers) {
            try {
                fn(type, data);
            } catch (_) {}
        }
    }

    function snapshot() {
        return {
            ...state,

            neighbors:
                [...state.neighbors],

            routes:
                [...state.routes],

            sessions:
                [...state.sessions],

            messages:
                [...state.messages],

            packets:
                [...state.packets],

            discovery:
                [...state.discovery],

            events:
                [...state.events],

            diagnostics:
                {
                    ...state.diagnostics,
                    attempted:
                        [
                            ...state.diagnostics.attempted
                        ]
                }
        };
    }

    function makeTimeout(ms) {
        if (
            typeof AbortController ===
            "undefined"
        ) {
            return {
                signal: undefined,
                cleanup() {}
            };
        }

        const controller =
            new AbortController();

        const timer =
            setTimeout(
                () => controller.abort(),
                ms
            );

        return {
            signal:
                controller.signal,

            cleanup() {
                clearTimeout(timer);
            }
        };
    }

    function errorText(error) {
        if (!error) {
            return "Unknown browser connection error.";
        }

        if (
            error.name ===
            "AbortError"
        ) {
            return "Request timed out.";
        }

        const message =
            String(
                error.message ||
                error
            );

        if (
            message.includes(
                "Failed to fetch"
            )
        ) {
            return (
                "Browser could not reach " +
                state.base +
                ". " +
                (
                    location.protocol === "https:"
                        ? "The page is HTTPS, so use the native HTTPS endpoint on port 49155. "
                        : ""
                ) +
                "Check that MeshBridge is running and that the endpoint is correct."
            );
        }

        return message;
    }

    async function request(
        path,
        options = {}
    ) {
        const url =
            normalizeBase(
                state.base
            ) +
            "/" +
            String(path)
                .replace(/^\/+/, "");

        const timer =
            makeTimeout(
                CONFIG.requestTimeout
            );

        const requestOptions = {
            cache:
                "no-store",

            credentials:
                "omit",

            ...options,

            headers: {
                Accept:
                    "application/json",

                ...(options.headers || {})
            }
        };

        if (timer.signal) {
            requestOptions.signal =
                timer.signal;
        }

        try {
            const response =
                await fetch(
                    url,
                    requestOptions
                );

            if (!response.ok) {
                throw new Error(
                    `MeshBridge HTTP ${response.status}`
                );
            }

            const text =
                await response.text();

            if (!text) {
                return {};
            }

            try {
                return JSON.parse(text);
            } catch (_) {
                return {
                    raw: text
                };
            }

        } catch (error) {

            throw new Error(
                errorText(error)
            );

        } finally {
            timer.cleanup();
        }
    }

    function candidateBases() {
        const configured =
            getBase();

        const candidates =
            [];

        function add(value) {
            value =
                normalizeBase(value);

            if (
                !candidates.includes(
                    value
                )
            ) {
                candidates.push(value);
            }
        }

        add(configured);

        if (
            location.protocol ===
            "https:"
        ) {
            add(HTTPS_LOCAL);

            /*
             * HTTP localhost is intentionally
             * last because HTTPS pages may
             * block active mixed content.
             */
            add(HTTP_LOCAL);
        } else {
            add(HTTP_LOCAL);
            add(HTTPS_LOCAL);
        }

        return candidates;
    }

    async function probe(base) {
        const previous =
            state.base;

        state.base =
            normalizeBase(base);

        try {
            const data =
                await request(
                    "/api/v1/status"
                );

            return {
                ok: true,
                data
            };

        } catch (error) {

            state.base =
                previous;

            return {
                ok: false,
                error
            };
        }
    }

    async function connect(
        preferredBase = null
    ) {
        const candidates =
            preferredBase
                ? [
                    normalizeBase(
                        preferredBase
                    )
                ]
                : candidateBases();

        state.diagnostics.attempted =
            [];

        for (
            const candidate of candidates
        ) {
            state.diagnostics.attempted
                .push(candidate);

            const result =
                await probe(
                    candidate
                );

            if (result.ok) {

                state.base =
                    candidate;

                state.diagnostics.selected =
                    candidate;

                state.connected =
                    true;

                state.online =
                    Boolean(
                        result.data &&
                        result.data.online
                    );

                state.status =
                    result.data;

                state.lastError =
                    null;

                state.lastUpdate =
                    Date.now();

                saveBase(candidate);

                emit(
                    "status",
                    snapshot()
                );

                return true;
            }
        }

        state.connected =
            false;

        state.online =
            false;

        state.diagnostics.selected =
            null;

        state.lastError =
            (
                "No reachable MeshBridge API endpoint. " +
                "Tried: " +
                state.diagnostics
                    .attempted
                    .join(", ")
            );

        emit(
            "offline",
            {
                ...snapshot(),
                base:
                    state.base,
                error:
                    state.lastError
            }
        );

        return false;
    }

    async function status() {
        const data =
            await request(
                "/api/v1/status"
            );

        state.status =
            data;

        state.connected =
            true;

        state.online =
            Boolean(
                data &&
                data.online
            );

        state.lastError =
            null;

        state.lastUpdate =
            Date.now();

        emit(
            "status",
            snapshot()
        );

        return data;
    }

    async function node() {
        const data =
            await request(
                "/api/v1/node"
            );

        state.node =
            data;

        return data;
    }

    async function neighbors() {
        const data =
            await request(
                "/api/v1/neighbors"
            );

        state.neighbors =
            Array.isArray(
                data.neighbors
            )
                ? data.neighbors
                : [];

        return data;
    }

    async function routes() {
        const data =
            await request(
                "/api/v1/routes"
            );

        state.routes =
            Array.isArray(
                data.routes
            )
                ? data.routes
                : [];

        return data;
    }

    async function sessions() {
        const data =
            await request(
                "/api/v1/sessions"
            );

        state.sessions =
            Array.isArray(
                data.sessions
            )
                ? data.sessions
                : [];

        return data;
    }

    async function messages() {
        const data =
            await request(
                "/api/v1/messages"
            );

        state.messages =
            Array.isArray(
                data.messages
            )
                ? data.messages
                : [];

        return data;
    }

    async function packets() {
        const data =
            await request(
                "/api/v1/packets"
            );

        state.packets =
            Array.isArray(
                data.packets
            )
                ? data.packets
                : [];

        return data;
    }

    async function discovery() {
        const data =
            await request(
                "/api/v1/discovery"
            );

        state.discovery =
            Array.isArray(
                data.known_nodes
            )
                ? data.known_nodes
                : [];

        return data;
    }

    async function topology() {
        const data =
            await request(
                "/api/v1/topology"
            );

        state.topology = {
            nodes:
                Array.isArray(
                    data.nodes
                )
                    ? data.nodes
                    : [],

            edges:
                Array.isArray(
                    data.edges
                )
                    ? data.edges
                    : (
                        Array.isArray(
                            data.links
                        )
                            ? data.links
                            : []
                    ),

            self:
                data.self || null
        };

        return data;
    }

    async function refreshDetails() {

        if (!state.connected) {
            const ok =
                await connect();

            if (!ok) {
                return false;
            }
        }

        try {

            await status();

            await Promise.allSettled([
                node(),
                neighbors(),
                routes(),
                sessions(),
                messages(),
                packets(),
                discovery(),
                topology()
            ]);

            state.lastUpdate =
                Date.now();

            emit(
                "data",
                snapshot()
            );

            return true;

        } catch (error) {

            state.connected =
                false;

            state.online =
                false;

            state.lastError =
                errorText(error);

            emit(
                "offline",
                {
                    ...snapshot(),
                    base:
                        state.base,
                    error:
                        state.lastError
                }
            );

            return false;
        }
    }

    async function refresh() {
        return refreshDetails();
    }

    async function send(
        target,
        message,
        priority = 2
    ) {
        if (!target) {
            throw new Error(
                "A target node ID is required."
            );
        }

        if (!message) {
            throw new Error(
                "A message is required."
            );
        }

        return request(
            "/api/v1/send",
            {
                method:
                    "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body:
                    JSON.stringify({
                        target,
                        message,
                        priority
                    })
            }
        );
    }

    function connectEvents() {

        if (
            state.eventSource
        ) {
            try {
                state.eventSource.close();
            } catch (_) {}

            state.eventSource =
                null;
        }

        if (
            !state.connected
        ) {
            return;
        }

        if (
            !(
                "EventSource"
                in window
            )
        ) {
            return;
        }

        const source =
            new EventSource(
                normalizeBase(
                    state.base
                ) +
                "/api/v1/events"
            );

        state.eventSource =
            source;

        source.onopen =
            () => {

                emit(
                    "event",
                    {
                        type:
                            "connection",
                        online:
                            true,
                        base:
                            state.base
                    }
                );
            };

        source.onmessage =
            event => {

                let data;

                try {
                    data =
                        JSON.parse(
                            event.data
                        );
                } catch (_) {
                    data = {
                        type:
                            "raw",
                        data:
                            event.data
                    };
                }

                state.events.push(
                    data
                );

                if (
                    state.events.length >
                    CONFIG.maxRows
                ) {
                    state.events =
                        state.events.slice(
                            -CONFIG.maxRows
                        );
                }

                emit(
                    "event",
                    data
                );

                emit(
                    "data",
                    snapshot()
                );
            };

        source.onerror =
            () => {

                emit(
                    "event",
                    {
                        type:
                            "sse-error",
                        online:
                            false,
                        base:
                            state.base
                    }
                );

                /*
                 * Do not immediately mark
                 * the API offline. The REST
                 * API can remain healthy
                 * while SSE reconnects.
                 */
            };
    }

    function stop() {

        for (
            const timer of
            state.timers
        ) {
            clearInterval(timer);
        }

        state.timers =
            [];

        if (
            state.eventSource
        ) {
            try {
                state.eventSource.close();
            } catch (_) {}

            state.eventSource =
                null;
        }
    }

    function start() {

        stop();

        state.base =
            getBase();

        connect()
            .then(
                ok => {

                    if (ok) {
                        connectEvents();
                        refreshDetails();
                    }
                }
            );

        state.timers.push(
            setInterval(
                () => {
                    refreshDetails();
                },
                CONFIG.detailInterval
            )
        );
    }

    function setBase(value) {

        const normalized =
            normalizeBase(value);

        state.base =
            normalized;

        saveBase(
            normalized
        );

        state.connected =
            false;

        state.online =
            false;

        state.lastError =
            null;

        emit(
            "endpoint",
            {
                base:
                    normalized
            }
        );

        return normalized;
    }

    function subscribe(fn) {

        if (
            typeof fn !==
            "function"
        ) {
            return () => {};
        }

        subscribers.add(fn);

        return () => {
            subscribers.delete(fn);
        };
    }

    function diagnostics() {

        return {
            ...state.diagnostics,

            currentBase:
                state.base,

            connected:
                state.connected,

            online:
                state.online,

            lastError:
                state.lastError
        };
    }

    window.MVXMeshBridge = {

        version:
            "3.1.1",

        apiVersion:
            "3.1.1",

        state,

        snapshot,

        diagnostics,

        connect,

        status,

        node,

        neighbors,

        routes,

        sessions,

        messages,

        packets,

        discovery,

        topology,

        refresh,

        refreshDetails,

        send,

        connectEvents,

        setBase,

        getBase,

        subscribe,

        start,

        stop
    };

    window.MVX_MESHBRIDGE_API_VERSION =
        "3.1.1";

    window.MVX_MESHBRIDGE_DEFAULT_BASE =
        DEFAULT_BASE;

    /*
     * Start after the page has had a
     * chance to install its listeners.
     */
    if (
        document.readyState ===
        "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            start,
            {
                once: true
            }
        );
    } else {
        start();
    }

})();
