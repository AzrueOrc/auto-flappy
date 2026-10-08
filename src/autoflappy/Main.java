package autoflappy;

public class Main {
    public static void main(String[] args) throws Exception {
        if (args.length > 0 && args[0].equalsIgnoreCase("--pixel8a")) {
            String config = args.length > 1 ? args[1] : "pixel8a-java/config.local.properties";
            new Pixel8aAutoFlappy(config).run();
            return;
        }
        AutoFlappy AF = new AutoFlappy();
        AF.run();
    }
}
