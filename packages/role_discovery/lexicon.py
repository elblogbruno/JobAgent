"""Capability lexicon and role signatures used by the deterministic fallback.

The LLM path produces richer graphs and roles. This module is what keeps the
feature working with no model configured, during tests, and whenever a model
returns something unusable. It is deliberately combination-driven: a role only
appears when several independent signals fire, never from a single keyword.
"""

from typing import Dict, List, NamedTuple

from packages.domain.enums import CapabilityKind


class LexiconEntry(NamedTuple):
    label: str
    kind: CapabilityKind
    aliases: tuple


K = CapabilityKind

CAPABILITY_LEXICON: List[LexiconEntry] = [
    # --- Technologies -----------------------------------------------------
    LexiconEntry("Unity", K.TECHNOLOGY, ("unity", "unity3d", "unity 3d")),
    LexiconEntry("Unreal Engine", K.TECHNOLOGY, ("unreal", "unreal engine", "ue4", "ue5")),
    LexiconEntry("C#", K.TECHNOLOGY, ("c#", "csharp", ".net")),
    LexiconEntry("C++", K.TECHNOLOGY, ("c++", "cpp")),
    LexiconEntry("Python", K.TECHNOLOGY, ("python",)),
    LexiconEntry("TypeScript", K.TECHNOLOGY, ("typescript", "javascript", "node.js", "nodejs")),
    LexiconEntry("Rust", K.TECHNOLOGY, ("rust",)),
    LexiconEntry("Swift", K.TECHNOLOGY, ("swift", "swiftui", "objective-c")),
    LexiconEntry("Kotlin", K.TECHNOLOGY, ("kotlin", "android sdk")),
    LexiconEntry("OpenXR", K.TECHNOLOGY, ("openxr", "oculus sdk", "meta xr sdk", "xr interaction")),
    LexiconEntry("ARKit", K.TECHNOLOGY, ("arkit", "realitykit", "arcore", "vuforia")),
    LexiconEntry("visionOS", K.TECHNOLOGY, ("visionos", "apple vision pro", "vision pro")),
    LexiconEntry("WebXR", K.TECHNOLOGY, ("webxr", "webgl", "three.js", "babylon.js", "a-frame")),
    LexiconEntry("OpenCV", K.TECHNOLOGY, ("opencv", "mediapipe")),
    LexiconEntry("PyTorch", K.TECHNOLOGY, ("pytorch", "tensorflow", "onnx", "keras")),
    LexiconEntry("CUDA", K.TECHNOLOGY, ("cuda", "tensorrt", "gpu compute")),
    LexiconEntry(
        "Shaders", K.TECHNOLOGY, ("shader", "hlsl", "glsl", "compute shader", "shadergraph")
    ),
    LexiconEntry("Vulkan / Metal", K.TECHNOLOGY, ("vulkan", "metal api", "directx", "opengl")),
    LexiconEntry("ROS", K.TECHNOLOGY, ("ros", "ros2", "robot operating system")),
    LexiconEntry(
        "Embedded / Firmware",
        K.TECHNOLOGY,
        ("firmware", "embedded", "esp32", "arduino", "raspberry pi", "stm32"),
    ),
    LexiconEntry("React", K.TECHNOLOGY, ("react", "next.js", "vue", "svelte")),
    LexiconEntry(
        "Cloud Infrastructure",
        K.TECHNOLOGY,
        ("aws", "gcp", "azure", "kubernetes", "docker", "terraform"),
    ),
    LexiconEntry(
        "Databases", K.TECHNOLOGY, ("postgres", "postgresql", "mysql", "mongodb", "redis", "sqlite")
    ),
    LexiconEntry(
        "LLM Tooling",
        K.TECHNOLOGY,
        ("llm", "openai api", "langchain", "rag", "prompt engineering", "gpt-4"),
    ),
    LexiconEntry(
        "Blender / 3D DCC", K.TECHNOLOGY, ("blender", "maya", "3ds max", "houdini", "substance")
    ),
    # --- Capabilities -----------------------------------------------------
    LexiconEntry(
        "Computer Vision",
        K.CAPABILITY,
        (
            "computer vision",
            "image processing",
            "object detection",
            "slam",
            "pose estimation",
            "hand tracking",
            "eye tracking",
        ),
    ),
    LexiconEntry(
        "Real-Time Graphics",
        K.CAPABILITY,
        (
            "real-time graphics",
            "real time rendering",
            "rendering pipeline",
            "graphics programming",
            "raytracing",
            "render pipeline",
        ),
    ),
    LexiconEntry(
        "Spatial Interaction Design",
        K.CAPABILITY,
        (
            "spatial interaction",
            "spatial ui",
            "3d interaction",
            "immersive ux",
            "spatial computing",
        ),
    ),
    LexiconEntry(
        "Machine Learning",
        K.CAPABILITY,
        ("machine learning", "deep learning", "neural network", "model training", "inference"),
    ),
    LexiconEntry(
        "Hardware Integration",
        K.CAPABILITY,
        (
            "hardware integration",
            "sensor",
            "depth camera",
            "imu",
            "calibration",
            "device driver",
            "peripheral",
        ),
    ),
    LexiconEntry(
        "Rapid Prototyping",
        K.CAPABILITY,
        ("prototype", "prototyping", "proof of concept", "poc", "mvp", "demo build"),
    ),
    LexiconEntry(
        "Performance Optimisation",
        K.CAPABILITY,
        ("optimisation", "optimization", "profiling", "frame rate", "latency", "memory budget"),
    ),
    LexiconEntry(
        "System Architecture",
        K.CAPABILITY,
        ("architecture", "system design", "scalable", "distributed system", "api design"),
    ),
    LexiconEntry(
        "Backend Engineering",
        K.CAPABILITY,
        ("backend", "microservice", "rest api", "graphql", "server-side"),
    ),
    LexiconEntry(
        "Frontend Engineering", K.CAPABILITY, ("frontend", "front-end", "ui development", "web app")
    ),
    LexiconEntry(
        "Mobile Engineering",
        K.CAPABILITY,
        ("ios app", "android app", "mobile app", "react native", "flutter"),
    ),
    LexiconEntry(
        "Applied Research",
        K.CAPABILITY,
        ("research", "paper", "publication", "experiment", "state of the art"),
    ),
    LexiconEntry(
        "Data Engineering",
        K.CAPABILITY,
        ("data pipeline", "etl", "data warehouse", "analytics pipeline"),
    ),
    LexiconEntry(
        "DevOps / Release",
        K.CAPABILITY,
        ("ci/cd", "continuous integration", "build pipeline", "release management", "deployment"),
    ),
    LexiconEntry(
        "Technical Writing",
        K.CAPABILITY,
        ("documentation", "technical writing", "developer docs", "tutorial"),
    ),
    # --- Domains ----------------------------------------------------------
    LexiconEntry(
        "XR / AR / VR",
        K.DOMAIN,
        (
            "xr",
            "augmented reality",
            "virtual reality",
            "mixed reality",
            " ar ",
            " vr ",
            "immersive",
            "headset",
            "hmd",
        ),
    ),
    LexiconEntry("Gaming", K.DOMAIN, ("game development", "gameplay", "game studio", "video game")),
    LexiconEntry("Robotics", K.DOMAIN, ("robotics", "drone", "autonomous vehicle", "uav")),
    LexiconEntry(
        "Healthcare", K.DOMAIN, ("healthcare", "medical", "clinical", "patient", "surgical")
    ),
    LexiconEntry(
        "Industrial / Manufacturing",
        K.DOMAIN,
        ("industrial", "manufacturing", "factory", "digital twin", "plant"),
    ),
    LexiconEntry(
        "Media & Entertainment",
        K.DOMAIN,
        ("entertainment", "broadcast", "film", "virtual production", "vfx"),
    ),
    LexiconEntry(
        "Interactive Installations",
        K.DOMAIN,
        (
            "installation",
            "exhibition",
            "museum",
            "experiential",
            "live event",
            "projection mapping",
        ),
    ),
    LexiconEntry(
        "Education", K.DOMAIN, ("education", "edtech", "training simulator", "e-learning")
    ),
    LexiconEntry("Fintech", K.DOMAIN, ("fintech", "payments", "banking", "trading")),
    LexiconEntry(
        "Developer Tools",
        K.DOMAIN,
        ("developer tools", "sdk", "toolchain", "internal tooling", "devtools"),
    ),
    LexiconEntry("Enterprise Software", K.DOMAIN, ("enterprise", "b2b saas", "crm", "erp")),
    LexiconEntry(
        "Consumer Products", K.DOMAIN, ("consumer app", "b2c", "consumer product", "retail")
    ),
    # --- Responsibilities -------------------------------------------------
    LexiconEntry(
        "Owning Delivery End to End",
        K.RESPONSIBILITY,
        ("end to end", "end-to-end", "ownership of", "owned the", "from concept to"),
    ),
    LexiconEntry(
        "Client & Stakeholder Management",
        K.RESPONSIBILITY,
        ("stakeholder", "client-facing", "customer meetings", "account", "consulting"),
    ),
    LexiconEntry(
        "Cross-Functional Collaboration",
        K.RESPONSIBILITY,
        ("cross-functional", "cross functional", "worked with design", "collaborated with"),
    ),
    LexiconEntry(
        "Hiring & Onboarding",
        K.RESPONSIBILITY,
        ("hiring", "recruiting", "interviewing candidates", "onboarding"),
    ),
    LexiconEntry(
        "Roadmap & Planning",
        K.RESPONSIBILITY,
        ("roadmap", "backlog", "sprint planning", "prioritisation", "prioritization"),
    ),
    LexiconEntry(
        "Budget & Vendor Management",
        K.RESPONSIBILITY,
        ("budget", "vendor", "procurement", "contract"),
    ),
    # --- Leadership -------------------------------------------------------
    LexiconEntry(
        "Team Leadership",
        K.LEADERSHIP,
        (
            "led a team",
            "team lead",
            "tech lead",
            "technical lead",
            "lead engineer",
            "leading a team",
            "managed a team",
            "line manager",
            "head of",
        ),
    ),
    LexiconEntry("Mentoring", K.LEADERSHIP, ("mentor", "mentoring", "coaching", "mentored")),
    LexiconEntry(
        "Technical Direction",
        K.LEADERSHIP,
        (
            "technical direction",
            "set the architecture",
            "technical strategy",
            "cto",
            "principal engineer",
            "staff engineer",
        ),
    ),
    # --- Product ownership ------------------------------------------------
    LexiconEntry(
        "Product Definition",
        K.PRODUCT_OWNERSHIP,
        (
            "product definition",
            "product strategy",
            "defined the product",
            "product owner",
            "product manager",
        ),
    ),
    LexiconEntry(
        "Founding Experience",
        K.PRODUCT_OWNERSHIP,
        ("founder", "co-founder", "cofounder", "founded", "founding", "started the company"),
    ),
    LexiconEntry(
        "Go-to-Market",
        K.PRODUCT_OWNERSHIP,
        ("go-to-market", "launch", "pricing", "customer discovery", "pitch"),
    ),
    LexiconEntry(
        "User Research",
        K.PRODUCT_OWNERSHIP,
        ("user research", "usability", "user testing", "playtest"),
    ),
    # --- Technical depth --------------------------------------------------
    LexiconEntry(
        "Low-Level Systems",
        K.TECHNICAL_DEPTH,
        (
            "low-level",
            "memory management",
            "multithreading",
            "concurrency",
            "native plugin",
            "assembly",
        ),
    ),
    LexiconEntry(
        "Algorithms & Maths",
        K.TECHNICAL_DEPTH,
        ("linear algebra", "quaternion", "geometry", "algorithm", "numerical", "kalman"),
    ),
    LexiconEntry(
        "Debugging Complex Systems",
        K.TECHNICAL_DEPTH,
        ("root cause", "debugging", "crash", "regression", "instrumentation"),
    ),
    LexiconEntry(
        "Testing & Quality",
        K.TECHNICAL_DEPTH,
        ("unit test", "integration test", "test coverage", "qa", "automated testing"),
    ),
    # --- Transferable -----------------------------------------------------
    LexiconEntry(
        "Public Speaking",
        K.TRANSFERABLE,
        ("speaker", "talk at", "conference talk", "keynote", "presented at"),
    ),
    LexiconEntry(
        "Teaching", K.TRANSFERABLE, ("teaching", "lecturer", "workshop", "course", "trainer")
    ),
    LexiconEntry(
        "Community Building",
        K.TRANSFERABLE,
        ("community", "meetup", "open source maintainer", "organiser", "organizer"),
    ),
    LexiconEntry(
        "Multilingual Communication",
        K.TRANSFERABLE,
        ("bilingual", "fluent in", "native speaker", "english", "spanish", "catalan"),
    ),
    LexiconEntry(
        "Entrepreneurship",
        K.TRANSFERABLE,
        ("startup", "bootstrapped", "grant", "accelerator", "investor"),
    ),
]


class RoleSignature(NamedTuple):
    """A role definition scored over a combination of capability signals.

    ``signals`` maps a capability label to its weight. ``min_signals`` forces a
    genuine combination: a role with one matching keyword never surfaces.
    """

    title: str
    family: str
    signals: Dict[str, float]
    min_signals: int
    industries: tuple
    company_types: tuple
    equivalent_titles: tuple
    aliases: tuple
    rationale: str


ROLE_SIGNATURES: List[RoleSignature] = [
    RoleSignature(
        "Spatial Computing Engineer",
        "XR & Spatial Computing",
        {
            "XR / AR / VR": 1.0,
            "Spatial Interaction Design": 0.9,
            "Unity": 0.7,
            "Computer Vision": 0.6,
            "Real-Time Graphics": 0.6,
            "visionOS": 0.5,
            "OpenXR": 0.5,
        },
        3,
        ("XR hardware", "Consumer electronics", "Enterprise XR", "Developer tools"),
        ("XR product companies", "Hardware platform teams", "Deep-tech startups"),
        ("Spatial Computing Engineer", "Spatial Software Engineer", "3D Interaction Engineer"),
        ("spatial computing",),
        "Combines immersive interaction work with real-time rendering and perception.",
    ),
    RoleSignature(
        "XR Engineer",
        "XR & Spatial Computing",
        {
            "XR / AR / VR": 1.0,
            "Unity": 0.8,
            "OpenXR": 0.6,
            "ARKit": 0.5,
            "Real-Time Graphics": 0.5,
            "Performance Optimisation": 0.4,
        },
        3,
        ("XR hardware", "Gaming", "Industrial XR", "Media & entertainment"),
        ("XR studios", "Platform teams", "Scale-ups"),
        ("AR Engineer", "VR Engineer", "AR/VR Software Engineer"),
        ("xr engineer",),
        "Direct match on immersive engineering with the engine and runtime stack.",
    ),
    RoleSignature(
        "Mixed Reality Engineer",
        "XR & Spatial Computing",
        {
            "XR / AR / VR": 1.0,
            "Hardware Integration": 0.8,
            "Computer Vision": 0.7,
            "Unity": 0.6,
            "Spatial Interaction Design": 0.6,
        },
        3,
        ("XR hardware", "Industrial", "Healthcare"),
        ("Hardware platform teams", "Applied research labs"),
        ("MR Engineer", "Passthrough Engineer", "Immersive Systems Engineer"),
        ("mixed reality",),
        "Blends perception and device work with immersive software.",
    ),
    RoleSignature(
        "Immersive Technology Engineer",
        "XR & Spatial Computing",
        {
            "XR / AR / VR": 0.9,
            "Interactive Installations": 0.8,
            "Rapid Prototyping": 0.7,
            "Real-Time Graphics": 0.6,
            "Hardware Integration": 0.5,
        },
        3,
        ("Media & entertainment", "Cultural institutions", "Experiential marketing"),
        ("Creative studios", "Agencies", "Cultural venues"),
        ("Immersive Experience Developer", "Interactive Technology Engineer"),
        ("immersive technology",),
        "Immersive engineering aimed at experiences rather than shipped products.",
    ),
    RoleSignature(
        "Creative Technologist",
        "Creative Technology",
        {
            "Interactive Installations": 1.0,
            "Rapid Prototyping": 0.9,
            "Unity": 0.6,
            "Computer Vision": 0.6,
            "Hardware Integration": 0.6,
            "XR / AR / VR": 0.5,
        },
        3,
        ("Advertising", "Cultural institutions", "Media & entertainment", "Retail"),
        ("Creative studios", "Agencies", "In-house innovation teams"),
        ("Creative Developer", "Experiential Technologist", "Interaction Developer"),
        ("creative technolog",),
        "Prototype-led work joining hardware, vision and real-time graphics.",
    ),
    RoleSignature(
        "Prototyping Engineer",
        "R&D and Prototyping",
        {
            "Rapid Prototyping": 1.0,
            "Hardware Integration": 0.7,
            "Applied Research": 0.6,
            "Unity": 0.4,
            "Computer Vision": 0.4,
            "Embedded / Firmware": 0.4,
        },
        3,
        ("Hardware", "Consumer electronics", "Robotics", "Deep tech"),
        ("R&D labs", "Hardware startups", "Innovation teams"),
        ("R&D Engineer", "Advanced Prototyping Engineer", "Concept Engineer"),
        ("prototyp",),
        "Fast concept-to-demo engineering across software and hardware.",
    ),
    RoleSignature(
        "Computer Vision Engineer",
        "Perception & ML",
        {
            "Computer Vision": 1.0,
            "OpenCV": 0.7,
            "Machine Learning": 0.6,
            "Python": 0.5,
            "Algorithms & Maths": 0.6,
            "CUDA": 0.4,
        },
        3,
        ("Robotics", "Healthcare", "Automotive", "XR hardware"),
        ("Deep-tech startups", "Research labs", "Platform teams"),
        ("Perception Engineer", "Vision Software Engineer", "Applied CV Engineer"),
        ("computer vision",),
        "Perception work backed by the maths and tooling it requires.",
    ),
    RoleSignature(
        "Graphics Engineer",
        "Graphics & Engine",
        {
            "Real-Time Graphics": 1.0,
            "Shaders": 0.8,
            "Vulkan / Metal": 0.7,
            "Performance Optimisation": 0.6,
            "Low-Level Systems": 0.5,
            "C++": 0.5,
        },
        3,
        ("Gaming", "XR hardware", "Media & entertainment", "Simulation"),
        ("Engine teams", "Game studios", "Platform teams"),
        ("Rendering Engineer", "Engine Programmer", "Real-Time Rendering Engineer"),
        ("graphics engineer", "rendering engineer"),
        "Rendering depth combined with low-level performance work.",
    ),
    RoleSignature(
        "XR Technical Lead",
        "Technical Leadership",
        {
            "XR / AR / VR": 0.9,
            "Team Leadership": 1.0,
            "Technical Direction": 0.9,
            "System Architecture": 0.7,
            "Unity": 0.5,
            "Mentoring": 0.5,
        },
        3,
        ("XR hardware", "Enterprise XR", "Media & entertainment"),
        ("Scale-ups", "Studios", "Platform teams"),
        ("Lead XR Engineer", "Head of XR Engineering", "Principal XR Engineer"),
        ("xr lead", "lead xr"),
        "Immersive expertise paired with real leadership responsibility.",
    ),
    RoleSignature(
        "Founding Engineer",
        "Startup Leadership",
        {
            "Founding Experience": 1.0,
            "Rapid Prototyping": 0.7,
            "System Architecture": 0.7,
            "Product Definition": 0.7,
            "Entrepreneurship": 0.6,
            "Owning Delivery End to End": 0.6,
        },
        3,
        ("Deep tech", "Developer tools", "Consumer products"),
        ("Pre-seed and seed startups", "Venture studios"),
        ("Founding Software Engineer", "Engineer #1", "Founding Member of Technical Staff"),
        ("founding engineer",),
        "Zero-to-one delivery ownership with product judgement attached.",
    ),
    RoleSignature(
        "Technical Product Manager",
        "Product",
        {
            "Product Definition": 1.0,
            "Roadmap & Planning": 0.8,
            "User Research": 0.6,
            "Client & Stakeholder Management": 0.6,
            "System Architecture": 0.5,
        },
        3,
        ("Developer tools", "Enterprise software", "Consumer products"),
        ("Scale-ups", "Product companies"),
        ("Product Manager, Technical", "Technical Program Manager"),
        ("product manager",),
        "Product ownership evidenced alongside technical depth.",
    ),
    RoleSignature(
        "Solutions Engineer",
        "Customer Engineering",
        {
            "Client & Stakeholder Management": 1.0,
            "Rapid Prototyping": 0.7,
            "Technical Writing": 0.5,
            "Developer Tools": 0.6,
            "Cross-Functional Collaboration": 0.5,
        },
        3,
        ("Developer tools", "Enterprise software", "XR hardware"),
        ("Platform vendors", "SDK companies"),
        ("Sales Engineer", "Field Engineer", "Developer Relations Engineer"),
        ("solutions engineer",),
        "Customer-facing engineering built on demo and integration work.",
    ),
    RoleSignature(
        "Machine Learning Engineer",
        "Perception & ML",
        {
            "Machine Learning": 1.0,
            "PyTorch": 0.8,
            "Python": 0.6,
            "Data Engineering": 0.5,
            "CUDA": 0.5,
            "Applied Research": 0.5,
        },
        3,
        ("AI products", "Healthcare", "Robotics", "Developer tools"),
        ("AI startups", "Research labs", "Platform teams"),
        ("Applied Scientist", "AI Engineer", "Deep Learning Engineer"),
        ("machine learning engineer",),
        "Model work supported by the tooling and data pipeline around it.",
    ),
    RoleSignature(
        "Robotics Software Engineer",
        "Robotics",
        {
            "Robotics": 1.0,
            "ROS": 0.8,
            "Computer Vision": 0.7,
            "Embedded / Firmware": 0.6,
            "C++": 0.5,
            "Algorithms & Maths": 0.5,
        },
        3,
        ("Robotics", "Industrial", "Automotive", "Logistics"),
        ("Robotics startups", "Industrial manufacturers"),
        ("Robotics Engineer", "Autonomy Engineer", "Perception & Controls Engineer"),
        ("robotics engineer",),
        "Robotics stack experience across perception, control and hardware.",
    ),
    RoleSignature(
        "Full-Stack Product Engineer",
        "Product Engineering",
        {
            "Frontend Engineering": 0.8,
            "Backend Engineering": 0.9,
            "React": 0.5,
            "Cloud Infrastructure": 0.5,
            "Databases": 0.5,
            "Owning Delivery End to End": 0.6,
        },
        3,
        ("Developer tools", "Consumer products", "Enterprise software"),
        ("Startups", "Product companies"),
        ("Full Stack Engineer", "Product Engineer", "Software Engineer"),
        ("full stack", "full-stack"),
        "End-to-end web product delivery across the stack.",
    ),
    RoleSignature(
        "Emerging Technology Engineer",
        "R&D and Prototyping",
        {
            "Applied Research": 0.9,
            "Rapid Prototyping": 0.8,
            "LLM Tooling": 0.6,
            "XR / AR / VR": 0.6,
            "Computer Vision": 0.5,
            "Hardware Integration": 0.5,
        },
        3,
        ("Innovation labs", "Consulting", "Media & entertainment", "Enterprise"),
        ("Innovation teams", "Consultancies", "Corporate R&D"),
        ("Innovation Engineer", "Advanced Technology Engineer", "Future Technologies Engineer"),
        ("emerging technolog",),
        "Exploratory engineering across whichever technology is next.",
    ),
]
