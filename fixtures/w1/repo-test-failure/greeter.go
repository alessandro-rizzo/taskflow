package greeter

func Greet(name string) string {
	if name == "" {
		return "Hello, stranger!"
	}
	return "Hello, " + name + "!"
}
